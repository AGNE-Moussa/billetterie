"""Appelant d'une route et contrôle de ses droits (rôles, scopes) dans un service FastAPI.

La gateway a déjà vérifié le jeton, mais un service ne croit jamais des en-têtes seuls : il
revérifie la signature du jeton transmis dans `Authorization`, localement, avec les clés du
realm en cache. `X-User-Id`, posé par le vérificateur, doit correspondre au jeton.

Utilisation dans un service :

    installer_auth(app, VerificateurJetons.depuis_jwks(jwks_url, emetteur, audience))

    @routeur.post("/api/v1/commandes")
    async def commander(appelant: Annotated[Appelant, Depends(exige_scopes("orders:write"))]):
        ...

Dans les tests, commun.faux_jetons fabrique des jetons signés par une clé de test.
"""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from commun.erreurs import ErreurMetier, reponse_probleme
from commun.jetons import ClesIndisponibles, JetonExpire, JetonInvalide, VerificateurJetons

ENTETE_UTILISATEUR = "X-User-Id"
# RFC 6750 : un 401 indique au client qu'un jeton Bearer est attendu.
DEFI_BEARER = {"WWW-Authenticate": 'Bearer realm="billetterie"'}

# Documente le schéma Bearer dans l'OpenAPI ; l'absence de jeton est gérée par `appelant`.
_bearer = HTTPBearer(auto_error=False, description="Jeton d'accès Keycloak du realm billetterie.")

# Réponses à déclarer sur une route : REPONSE_NON_AUTHENTIFIE si elle exige seulement un
# appelant (AppelantDep), REPONSES_AUTH si elle exige aussi un rôle ou un scope.
REPONSE_NON_AUTHENTIFIE: dict[int | str, dict[str, Any]] = {
    401: reponse_probleme("Jeton absent, invalide ou expiré (JETON_*)."),
}
REPONSES_AUTH: dict[int | str, dict[str, Any]] = {
    **REPONSE_NON_AUTHENTIFIE,
    403: reponse_probleme("Rôle ou scope manquant (ROLE_MANQUANT, SCOPE_MANQUANT)."),
}


@dataclass(frozen=True)
class Appelant:
    """Qui appelle la route : utilisateur (ou compte de service), rôles, scopes et client."""

    identifiant: str
    roles: frozenset[str]
    scopes: frozenset[str]
    client: str

    @classmethod
    def depuis_claims(cls, claims: dict[str, Any]) -> "Appelant":
        roles = claims.get("realm_access", {}).get("roles", [])
        return cls(
            identifiant=str(claims["sub"]),
            roles=frozenset(str(role) for role in roles),
            scopes=frozenset(str(claims.get("scope", "")).split()),
            client=str(claims.get("azp", "")),
        )


def installer_auth(app: FastAPI, verificateur: VerificateurJetons) -> None:
    """Rend le vérificateur de jetons disponible pour la dépendance `appelant`."""
    app.state.verificateur_jetons = verificateur


def _non_authentifie(code: str, detail: str) -> ErreurMetier:
    return ErreurMetier(code, 401, detail, titre="Authentification requise", entetes=DEFI_BEARER)


async def appelant(
    requete: Request,
    identifiants: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Appelant:
    """Dépendance : l'appelant authentifié de la requête, après revérification du jeton."""
    if identifiants is None or identifiants.scheme.lower() != "bearer":
        raise _non_authentifie("JETON_ABSENT", "Jeton Bearer absent.")
    verificateur: VerificateurJetons = requete.app.state.verificateur_jetons
    try:
        claims = await verificateur.verifier(identifiants.credentials)
    except JetonExpire as erreur:
        raise _non_authentifie("JETON_EXPIRE", "Le jeton d'accès a expiré.") from erreur
    except JetonInvalide as erreur:
        raise _non_authentifie("JETON_INVALIDE", "Le jeton d'accès est refusé.") from erreur
    except ClesIndisponibles as erreur:
        raise ErreurMetier(
            "VERIFICATION_INDISPONIBLE",
            503,
            "Les clés du realm ne sont pas encore disponibles.",
            titre="Vérification indisponible",
        ) from erreur

    resultat = Appelant.depuis_claims(claims)
    # L'en-tête de la gateway et le jeton doivent désigner la même personne.
    annonce = requete.headers.get(ENTETE_UTILISATEUR)
    if annonce is not None and annonce != resultat.identifiant:
        raise _non_authentifie("JETON_INVALIDE", "Le jeton ne correspond pas à l'appelant annoncé.")
    return resultat


AppelantDep = Annotated[Appelant, Depends(appelant)]


def exige_scopes(*scopes: str) -> Callable[[Appelant], Awaitable[Appelant]]:
    """Dépendance : l'appelant doit avoir tous les scopes demandés, sinon 403."""
    attendus = frozenset(scopes)

    async def controle(appelant: AppelantDep) -> Appelant:
        manquants = attendus - appelant.scopes
        if manquants:
            raise ErreurMetier(
                "SCOPE_MANQUANT",
                403,
                f"Scope requis : {', '.join(sorted(manquants))}.",
                titre="Accès refusé",
            )
        return appelant

    return controle


def exige_role(*roles: str) -> Callable[[Appelant], Awaitable[Appelant]]:
    """Dépendance : l'appelant doit avoir au moins un des rôles demandés, sinon 403."""
    acceptes = frozenset(roles)

    async def controle(appelant: AppelantDep) -> Appelant:
        if not acceptes & appelant.roles:
            raise ErreurMetier(
                "ROLE_MANQUANT",
                403,
                f"Rôle requis : {_liste(sorted(acceptes))}.",
                titre="Accès refusé",
            )
        return appelant

    return controle


def _liste(valeurs: Iterable[str]) -> str:
    return " ou ".join(valeurs)
