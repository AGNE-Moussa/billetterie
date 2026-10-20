"""Application du vérificateur, appelée par le middleware ForwardAuth de Traefik.

Traefik envoie à `/verifier` les en-têtes de la requête d'origine, dont `Authorization`, et la
décrit par `X-Forwarded-Method` et `X-Forwarded-Uri`. Une réponse 2xx laisse passer la requête,
avec les en-têtes `X-User-*` et `X-Client-Id` recopiés vers le service (authResponseHeaders) ;
toute autre réponse est renvoyée telle quelle au client, sans que le service soit appelé.

Lancement : uvicorn --factory verificateur.principal:creer_app
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from commun.jetons import (
    ClesIndisponibles,
    JetonExpire,
    JetonInvalide,
    VerificateurJetons,
    jeton_bearer,
)
from verificateur import routes_publiques
from verificateur.config import Parametres, parametres

TYPE_MEDIA = "application/problem+json"


def _probleme(statut: int, titre: str, detail: str, code: str) -> JSONResponse:
    reponse = JSONResponse(
        {"type": "about:blank", "title": titre, "status": statut, "detail": detail, "code": code},
        status_code=statut,
        media_type=TYPE_MEDIA,
    )
    if statut == 401:
        # RFC 6750 : le client apprend qu'un jeton Bearer est attendu.
        reponse.headers["WWW-Authenticate"] = 'Bearer realm="billetterie"'
    return reponse


def creer_app(
    config: Parametres | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    config = config or parametres()
    publiques = routes_publiques.analyser(config.routes_publiques)
    verificateur = VerificateurJetons.depuis_jwks(
        config.jwks_url,
        config.jwt_emetteur,
        config.jwt_audience,
        duree_cache=config.jwks_duree_cache,
        intervalle_min=config.jwks_intervalle_min,
        transport=transport,
    )

    @asynccontextmanager
    async def cycle_de_vie(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await verificateur.aclose()

    app = FastAPI(
        title="Vérificateur de jetons", version="0.1.0", lifespan=cycle_de_vie, openapi_url=None
    )

    @app.get("/health")
    async def sante() -> dict[str, str]:
        return {"statut": "ok"}

    # Traefik appelle toujours en GET ; les autres méthodes sont acceptées par prudence.
    @app.api_route("/verifier", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
    async def verifier(requete: Request) -> Response:
        jeton = jeton_bearer(requete.headers.get("Authorization"))
        if jeton is None:
            methode = requete.headers.get("X-Forwarded-Method", "")
            uri = requete.headers.get("X-Forwarded-Uri", "/")
            if routes_publiques.est_publique(publiques, methode, uri):
                return Response(status_code=200)
            return _probleme(
                401, "Authentification requise", "Jeton Bearer absent.", "JETON_ABSENT"
            )

        try:
            claims = await verificateur.verifier(jeton)
        except JetonExpire:
            return _probleme(401, "Jeton expiré", "Le jeton d'accès a expiré.", "JETON_EXPIRE")
        except JetonInvalide:
            return _probleme(
                401, "Jeton invalide", "Le jeton d'accès est refusé.", "JETON_INVALIDE"
            )
        except ClesIndisponibles:
            return _probleme(
                503,
                "Vérification indisponible",
                "Les clés du realm ne sont pas encore disponibles.",
                "VERIFICATION_INDISPONIBLE",
            )

        return Response(
            status_code=200,
            headers={
                "X-User-Id": str(claims["sub"]),
                "X-User-Roles": ",".join(claims.get("realm_access", {}).get("roles", [])),
                "X-Client-Id": str(claims.get("azp", "")),
            },
        )

    return app
