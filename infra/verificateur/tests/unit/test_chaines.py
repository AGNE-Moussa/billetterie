"""Une vérification de jeton par chaîne Traefik (plan BIL-012, CA3, décision Q2, question 2 et
H3 du plan).

`/verifier` sert la chaîne `standard@file` et refuse le rôle `partner` (un revendeur ne
contourne pas son quota) ; `/verifier/partenaires` sert la chaîne `partenaires@file` et
n'admet que le rôle `partner`. Sans jeton, une route publique passe sur les deux.
"""

from collections.abc import AsyncIterator

import httpx
import pytest

from commun.faux_jetons import URL_JWKS_TEST, EmetteurDeTest
from verificateur.config import Parametres
from verificateur.principal import creer_app

pytestmark = pytest.mark.anyio

STANDARD = "/verifier"
PARTENAIRES = "/verifier/partenaires"
ROUTE_PUBLIQUE = "/api/v1/events"
ROUTE_PROTEGEE = "/api/v1/orders"
ENTETES_IDENTITE = ("X-User-Id", "X-User-Roles", "X-Client-Id")


@pytest.fixture
def emetteur() -> EmetteurDeTest:
    return EmetteurDeTest()


@pytest.fixture
async def client(emetteur: EmetteurDeTest) -> AsyncIterator[httpx.AsyncClient]:
    parametres = Parametres(
        jwt_emetteur=emetteur.emetteur,
        jwt_audience=emetteur.audience,
        jwks_url=URL_JWKS_TEST,
        routes_publiques=f"GET {ROUTE_PUBLIQUE}",
    )
    app = creer_app(parametres, transport=emetteur.transport())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _appel(
    jeton: str | None = None, methode: str = "GET", uri: str = ROUTE_PROTEGEE
) -> dict[str, str]:
    """En-têtes envoyés par Traefik pour une requête d'origine."""
    entetes = {"X-Forwarded-Method": methode, "X-Forwarded-Uri": uri}
    if jeton is not None:
        entetes["Authorization"] = f"Bearer {jeton}"
    return entetes


def _jeton_partner(emetteur: EmetteurDeTest) -> str:
    return emetteur.jeton(
        sujet="service-account-revendeur-test",
        roles=["partner"],
        scopes=["events:read", "orders:read", "orders:write", "tickets:read"],
        client="revendeur-test",
    )


def _assert_role_manquant(reponse: httpx.Response) -> None:
    assert reponse.status_code == 403, reponse.text
    assert reponse.headers["content-type"] == "application/problem+json"
    corps = reponse.json()
    assert corps["code"] == "ROLE_MANQUANT"
    assert corps["status"] == 403
    for entete in ENTETES_IDENTITE:
        assert entete not in reponse.headers


async def test_un_jeton_partner_sur_la_chaine_standard_renvoie_403_role_manquant(
    client: httpx.AsyncClient, emetteur: EmetteurDeTest
) -> None:
    reponse = await client.get(STANDARD, headers=_appel(_jeton_partner(emetteur)))

    _assert_role_manquant(reponse)


async def test_un_jeton_partner_sur_une_route_publique_de_la_chaine_standard_renvoie_403(
    client: httpx.AsyncClient, emetteur: EmetteurDeTest
) -> None:
    reponse = await client.get(
        STANDARD, headers=_appel(_jeton_partner(emetteur), uri=ROUTE_PUBLIQUE)
    )

    _assert_role_manquant(reponse)


async def test_un_jeton_customer_sur_la_chaine_standard_passe_avec_son_identite(
    client: httpx.AsyncClient, emetteur: EmetteurDeTest
) -> None:
    jeton = emetteur.jeton(
        sujet="client-a", roles=["customer"], scopes=["orders:read"], client="frontend"
    )

    reponse = await client.get(STANDARD, headers=_appel(jeton))

    assert reponse.status_code == 200, reponse.text
    assert reponse.headers["X-User-Id"] == "client-a"
    assert "customer" in reponse.headers["X-User-Roles"].split(",")


async def test_un_jeton_partner_sur_la_chaine_partenaires_passe_avec_son_identite(
    client: httpx.AsyncClient, emetteur: EmetteurDeTest
) -> None:
    reponse = await client.get(PARTENAIRES, headers=_appel(_jeton_partner(emetteur)))

    assert reponse.status_code == 200, reponse.text
    assert reponse.headers["X-User-Id"] == "service-account-revendeur-test"
    assert "partner" in reponse.headers["X-User-Roles"].split(",")
    assert reponse.headers["X-Client-Id"] == "revendeur-test"


@pytest.mark.parametrize(
    ("roles", "client_jeton"),
    [
        pytest.param(["customer"], "frontend", id="customer"),
        pytest.param(["admin"], "frontend", id="admin"),
        pytest.param([], "services", id="services"),
    ],
)
async def test_un_jeton_sans_role_partner_sur_la_chaine_partenaires_renvoie_403(
    client: httpx.AsyncClient, emetteur: EmetteurDeTest, roles: list[str], client_jeton: str
) -> None:
    jeton = emetteur.jeton(sujet="appelant-test", roles=roles, client=client_jeton)

    reponse = await client.get(PARTENAIRES, headers=_appel(jeton))

    _assert_role_manquant(reponse)


@pytest.mark.parametrize("chaine", [STANDARD, PARTENAIRES])
async def test_sans_jeton_une_route_publique_passe_sur_les_deux_chaines(
    client: httpx.AsyncClient, chaine: str
) -> None:
    publique = await client.get(chaine, headers=_appel(uri=ROUTE_PUBLIQUE))
    protegee = await client.get(chaine, headers=_appel(uri=ROUTE_PROTEGEE))

    assert publique.status_code == 200, publique.text
    assert "X-User-Id" not in publique.headers
    assert protegee.status_code == 401, protegee.text
    assert protegee.json()["code"] == "JETON_ABSENT"
