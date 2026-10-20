"""Vérificateur sans Keycloak : jetons signés par une clé de test, JWKS servi en mémoire."""

import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from verificateur.config import Parametres
from verificateur.principal import creer_app

pytestmark = pytest.mark.anyio

EMETTEUR = "http://localhost/auth/realms/billetterie"
AUDIENCE = "billetterie-api"
URL_JWKS = "http://keycloak/certs"
KID = "cle-de-test"


def _cle_privee() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


CLE = _cle_privee()
AUTRE_CLE = _cle_privee()


def _jwk(cle: rsa.RSAPrivateKey, kid: str, usage: str = "sig") -> dict[str, Any]:
    publique: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(cle.public_key()))
    return {**publique, "kid": kid, "use": usage, "alg": "RS256"}


def _jeton(cle: rsa.RSAPrivateKey = CLE, kid: str = KID, **remplacements: Any) -> str:
    maintenant = int(time.time())
    contenu = {
        "iss": EMETTEUR,
        "aud": [AUDIENCE, "account"],
        "sub": "utilisateur-42",
        "azp": "frontend",
        "iat": maintenant,
        "exp": maintenant + 300,
        "realm_access": {"roles": ["customer", "default-roles-billetterie"]},
    }
    contenu.update(remplacements)
    return jwt.encode(contenu, cle, algorithm="RS256", headers={"kid": kid})


class FauxKeycloak:
    """Sert le JWKS et compte les appels : la validation doit rester locale."""

    def __init__(self) -> None:
        self.cles = [_jwk(CLE, KID), _jwk(AUTRE_CLE, "cle-de-chiffrement", usage="enc")]
        self.appels = 0
        self.en_panne = False

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        self.appels += 1
        if self.en_panne:
            return httpx.Response(503)
        return httpx.Response(200, json={"keys": self.cles})


@pytest.fixture
def keycloak() -> FauxKeycloak:
    return FauxKeycloak()


@pytest.fixture
def fabrique(
    keycloak: FauxKeycloak,
) -> Callable[..., httpx.AsyncClient]:
    def creer(**config: Any) -> httpx.AsyncClient:
        parametres = Parametres(
            jwt_emetteur=EMETTEUR,
            jwt_audience=AUDIENCE,
            jwks_url=URL_JWKS,
            **config,
        )
        app = creer_app(parametres, transport=httpx.MockTransport(keycloak))
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    return creer


@pytest.fixture
async def client(fabrique: Callable[..., httpx.AsyncClient]) -> AsyncIterator[httpx.AsyncClient]:
    async with fabrique(routes_publiques="GET /api/v1/evenements") as client:
        yield client


def _appel(
    jeton: str | None = None, methode: str = "GET", uri: str = "/api/v1/commandes"
) -> dict[str, str]:
    """En-têtes envoyés par Traefik pour une requête d'origine."""
    entetes = {"X-Forwarded-Method": methode, "X-Forwarded-Uri": uri}
    if jeton is not None:
        entetes["Authorization"] = f"Bearer {jeton}"
    return entetes


async def test_un_jeton_valide_donne_l_identite_en_en_tetes(client: httpx.AsyncClient) -> None:
    reponse = await client.get("/verifier", headers=_appel(_jeton()))

    assert reponse.status_code == 200
    assert reponse.headers["X-User-Id"] == "utilisateur-42"
    assert reponse.headers["X-User-Roles"] == "customer,default-roles-billetterie"
    assert reponse.headers["X-Client-Id"] == "frontend"


async def test_sans_jeton_une_route_protegee_repond_401(client: httpx.AsyncClient) -> None:
    reponse = await client.get("/verifier", headers=_appel())

    assert reponse.status_code == 401
    assert reponse.headers["content-type"] == "application/problem+json"
    assert reponse.headers["WWW-Authenticate"].startswith("Bearer")
    assert reponse.json()["code"] == "JETON_ABSENT"


async def test_un_jeton_expire_est_refuse(client: httpx.AsyncClient) -> None:
    passe = int(time.time()) - 3600
    reponse = await client.get("/verifier", headers=_appel(_jeton(iat=passe, exp=passe + 300)))

    assert reponse.status_code == 401
    assert reponse.json()["code"] == "JETON_EXPIRE"


@pytest.mark.parametrize(
    "jeton",
    [
        pytest.param(lambda: _jeton(cle=AUTRE_CLE), id="mauvaise-signature"),
        pytest.param(lambda: _jeton(iss="http://pirate.exemple/realms/billetterie"), id="emetteur"),
        pytest.param(lambda: _jeton(aud="account"), id="audience"),
        pytest.param(lambda: _jeton(kid="cle-inconnue"), id="cle-inconnue"),
        pytest.param(lambda: _jeton(kid="cle-de-chiffrement", cle=AUTRE_CLE), id="cle-enc"),
        pytest.param(
            lambda: jwt.encode({"sub": "x"}, "s" * 32, algorithm="HS256", headers={"kid": KID}),
            id="hs256",
        ),
        pytest.param(lambda: "pas-un-jwt", id="mal-forme"),
    ],
)
async def test_un_jeton_invalide_est_refuse(
    client: httpx.AsyncClient, jeton: Callable[[], str]
) -> None:
    reponse = await client.get("/verifier", headers=_appel(jeton()))

    assert reponse.status_code == 401
    assert reponse.json()["code"] == "JETON_INVALIDE"
    assert "X-User-Id" not in reponse.headers


async def test_un_autre_schema_que_bearer_compte_comme_absent(client: httpx.AsyncClient) -> None:
    reponse = await client.get(
        "/verifier", headers={**_appel(), "Authorization": "Basic dXRpbGlzYXRldXI6bWRw"}
    )

    assert reponse.json()["code"] == "JETON_ABSENT"


@pytest.mark.parametrize(
    "uri", ["/api/v1/evenements", "/api/v1/evenements/42", "/api/v1/evenements?page=2"]
)
async def test_une_route_publique_passe_sans_jeton_et_sans_identite(
    client: httpx.AsyncClient, uri: str
) -> None:
    reponse = await client.get("/verifier", headers=_appel(uri=uri))

    assert reponse.status_code == 200
    assert "X-User-Id" not in reponse.headers


@pytest.mark.parametrize(
    ("methode", "uri"),
    [
        ("POST", "/api/v1/evenements"),
        ("GET", "/api/v1/evenementsX"),
        ("GET", "/api/v1/evenements/../commandes"),
        ("GET", "/api/v1/evenements/%2e%2e/commandes"),
    ],
)
async def test_hors_des_routes_publiques_le_jeton_est_exige(
    client: httpx.AsyncClient, methode: str, uri: str
) -> None:
    reponse = await client.get("/verifier", headers=_appel(methode=methode, uri=uri))

    assert reponse.status_code == 401


async def test_un_jeton_fourni_sur_une_route_publique_est_verifie(
    client: httpx.AsyncClient,
) -> None:
    uri = "/api/v1/evenements"
    valide = await client.get("/verifier", headers=_appel(_jeton(), uri=uri))
    invalide = await client.get("/verifier", headers=_appel(_jeton(cle=AUTRE_CLE), uri=uri))

    assert valide.headers["X-User-Id"] == "utilisateur-42"
    assert invalide.status_code == 401


async def test_les_cles_sont_chargees_une_fois_pour_toutes_les_requetes(
    client: httpx.AsyncClient, keycloak: FauxKeycloak
) -> None:
    for _ in range(20):
        assert (await client.get("/verifier", headers=_appel(_jeton()))).status_code == 200

    assert keycloak.appels == 1


async def test_une_nouvelle_cle_du_realm_est_prise_en_compte(
    fabrique: Callable[..., httpx.AsyncClient], keycloak: FauxKeycloak
) -> None:
    async with fabrique(jwks_intervalle_min=0) as client:
        assert (await client.get("/verifier", headers=_appel(_jeton()))).status_code == 200

        # Rotation : Keycloak signe désormais avec une nouvelle clé.
        keycloak.cles.append(_jwk(AUTRE_CLE, "nouvelle-cle"))
        reponse = await client.get("/verifier", headers=_appel(_jeton(AUTRE_CLE, "nouvelle-cle")))

    assert reponse.status_code == 200
    assert keycloak.appels == 2


async def test_des_kid_inventes_ne_font_pas_appeler_keycloak_en_boucle(
    client: httpx.AsyncClient, keycloak: FauxKeycloak
) -> None:
    await client.get("/verifier", headers=_appel(_jeton()))
    for numero in range(10):
        await client.get("/verifier", headers=_appel(_jeton(kid=f"invente-{numero}")))

    # Premier chargement, puis rechargements limités à un toutes les 10 secondes.
    assert keycloak.appels == 1


async def test_sans_cles_disponibles_le_verificateur_repond_503(
    client: httpx.AsyncClient, keycloak: FauxKeycloak
) -> None:
    keycloak.en_panne = True

    reponse = await client.get("/verifier", headers=_appel(_jeton()))

    assert reponse.status_code == 503
    assert reponse.json()["code"] == "VERIFICATION_INDISPONIBLE"


async def test_les_cles_connues_restent_utilisees_si_keycloak_tombe(
    fabrique: Callable[..., httpx.AsyncClient], keycloak: FauxKeycloak
) -> None:
    async with fabrique(jwks_duree_cache=0, jwks_intervalle_min=0) as client:
        assert (await client.get("/verifier", headers=_appel(_jeton()))).status_code == 200
        keycloak.en_panne = True
        reponse = await client.get("/verifier", headers=_appel(_jeton()))

    assert reponse.status_code == 200


def test_une_route_publique_mal_formee_arrete_le_demarrage() -> None:
    parametres = Parametres(
        jwt_emetteur=EMETTEUR, jwks_url=URL_JWKS, routes_publiques="GET api/v1/evenements"
    )

    with pytest.raises(ValueError, match="mal formée"):
        creer_app(parametres)
