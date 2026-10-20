"""Appelant, rôles et scopes (commun.auth) avec des jetons de test (commun.faux_jetons)."""

from collections.abc import AsyncIterator
from typing import Annotated

import httpx
import pytest
from fastapi import Depends, FastAPI

from commun.auth import (
    Appelant,
    AppelantDep,
    appelant,
    exige_role,
    exige_scopes,
    installer_auth,
)
from commun.erreurs import installer_erreurs
from commun.faux_jetons import EmetteurDeTest
from commun.jetons import VerificateurJetons

pytestmark = pytest.mark.anyio


@pytest.fixture
def emetteur() -> EmetteurDeTest:
    return EmetteurDeTest()


def _app(verificateur: VerificateurJetons) -> FastAPI:
    app = FastAPI()
    installer_erreurs(app)
    installer_auth(app, verificateur)

    @app.get("/moi")
    async def moi(appelant: AppelantDep) -> dict[str, object]:
        return {
            "identifiant": appelant.identifiant,
            "roles": sorted(appelant.roles),
            "scopes": sorted(appelant.scopes),
            "client": appelant.client,
        }

    @app.post("/commandes")
    async def commander(
        _appelant: Annotated[Appelant, Depends(exige_scopes("orders:read", "orders:write"))],
    ) -> None:
        return None

    @app.delete("/seances")
    async def annuler(_appelant: Annotated[Appelant, Depends(exige_role("admin"))]) -> None:
        return None

    @app.get("/lots")
    async def lots(
        _appelant: Annotated[Appelant, Depends(exige_role("partner", "admin"))],
    ) -> None:
        return None

    return app


@pytest.fixture
async def client(emetteur: EmetteurDeTest) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=_app(emetteur.verificateur()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_l_appelant_est_lu_dans_le_jeton_verifie(
    client: httpx.AsyncClient, emetteur: EmetteurDeTest
) -> None:
    jeton = emetteur.entetes(
        sujet="revendeur-7", roles=["partner"], scopes=["events:read", "orders:write"], client="lot"
    )

    reponse = await client.get("/moi", headers=jeton)

    assert reponse.json() == {
        "identifiant": "revendeur-7",
        "roles": ["partner"],
        "scopes": ["events:read", "orders:write"],
        "client": "lot",
    }


async def test_x_user_id_coherent_avec_le_jeton_est_accepte(
    client: httpx.AsyncClient, emetteur: EmetteurDeTest
) -> None:
    entetes = {**emetteur.entetes(sujet="client-1"), "X-User-Id": "client-1"}

    assert (await client.get("/moi", headers=entetes)).status_code == 200


@pytest.mark.parametrize(
    ("scopes", "statut"),
    [
        (["orders:read", "orders:write"], 200),
        (["orders:read", "orders:write", "events:read"], 200),
        (["orders:read"], 403),
        ([], 403),
    ],
)
async def test_tous_les_scopes_demandes_sont_exiges(
    client: httpx.AsyncClient, emetteur: EmetteurDeTest, scopes: list[str], statut: int
) -> None:
    reponse = await client.post("/commandes", headers=emetteur.entetes(scopes=scopes))

    assert reponse.status_code == statut


async def test_un_scope_manquant_donne_un_403_problem_details(
    client: httpx.AsyncClient, emetteur: EmetteurDeTest
) -> None:
    reponse = await client.post(
        "/commandes",
        headers={**emetteur.entetes(scopes=["orders:read"]), "X-Correlation-Id": "requete-9"},
    )

    assert reponse.status_code == 403
    assert reponse.headers["content-type"] == "application/problem+json"
    assert reponse.json() == {
        "type": "about:blank",
        "title": "Accès refusé",
        "status": 403,
        "detail": "Scope requis : orders:write.",
        "code": "SCOPE_MANQUANT",
    }


@pytest.mark.parametrize(
    ("roles", "statut"), [(["admin"], 200), (["customer"], 403), (["customer", "admin"], 200)]
)
async def test_exige_role(
    client: httpx.AsyncClient, emetteur: EmetteurDeTest, roles: list[str], statut: int
) -> None:
    reponse = await client.delete("/seances", headers=emetteur.entetes(roles=roles))

    assert reponse.status_code == statut
    if statut == 403:
        assert reponse.json()["code"] == "ROLE_MANQUANT"


@pytest.mark.parametrize(("roles", "statut"), [(["partner"], 200), (["admin"], 200), ([], 403)])
async def test_exige_role_accepte_un_des_roles(
    client: httpx.AsyncClient, emetteur: EmetteurDeTest, roles: list[str], statut: int
) -> None:
    assert (await client.get("/lots", headers=emetteur.entetes(roles=roles))).status_code == statut


@pytest.mark.parametrize(
    ("entetes", "code"),
    [
        ({}, "JETON_ABSENT"),
        ({"Authorization": "Basic dXRpbGlzYXRldXI6bWRw"}, "JETON_ABSENT"),
        ({"Authorization": "Bearer pas-un-jwt"}, "JETON_INVALIDE"),
    ],
)
async def test_sans_jeton_valide_l_appelant_recoit_401(
    client: httpx.AsyncClient, entetes: dict[str, str], code: str
) -> None:
    reponse = await client.get("/moi", headers=entetes)

    assert reponse.status_code == 401
    assert reponse.headers["WWW-Authenticate"] == 'Bearer realm="billetterie"'
    assert reponse.json()["code"] == code


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "http://pirate.exemple/realms/billetterie"},
        {"aud": "account"},
    ],
)
async def test_un_jeton_d_un_autre_emetteur_ou_d_une_autre_audience_recoit_401(
    client: httpx.AsyncClient, emetteur: EmetteurDeTest, claims: dict[str, str]
) -> None:
    reponse = await client.get("/moi", headers=emetteur.entetes(**claims))

    assert reponse.json()["code"] == "JETON_INVALIDE"


async def test_sans_cles_du_realm_le_service_repond_503(emetteur: EmetteurDeTest) -> None:
    def en_panne(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("panne", request=requete)

    verificateur = VerificateurJetons.depuis_jwks(
        "http://keycloak/certs",
        emetteur.emetteur,
        emetteur.audience,
        transport=httpx.MockTransport(en_panne),
    )
    transport = httpx.ASGITransport(app=_app(verificateur))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.get("/moi", headers=emetteur.entetes())
    await verificateur.aclose()

    assert reponse.status_code == 503
    assert reponse.json()["code"] == "VERIFICATION_INDISPONIBLE"


async def test_les_tests_peuvent_aussi_remplacer_l_appelant_directement() -> None:
    """Autre façon de simuler un appelant (CA2) : remplacer la dépendance `appelant`."""
    app = _app(EmetteurDeTest().verificateur())
    app.dependency_overrides[appelant] = lambda: Appelant(
        "admin-1", frozenset({"admin"}), frozenset(), "frontend"
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.delete("/seances")).status_code == 200
