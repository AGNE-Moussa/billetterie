"""Routes du service echo, sans base ni Keycloak : dépôt en mémoire, jetons de test."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest

from commun.faux_jetons import EmetteurDeTest
from echo.api.dependances import obtenir_depot
from echo.config import Parametres
from echo.domaine.echos import DepotEchos, Echo, EchoDejaExistant
from echo.principal import creer_app

pytestmark = pytest.mark.anyio

INSTANCE = "echo-test"


class DepotEnMemoire:
    def __init__(self) -> None:
        self.echos: dict[str, Echo] = {}

    async def ajouter(self, message: str) -> Echo:
        if message in self.echos:
            raise EchoDejaExistant(message)
        self.echos[message] = Echo(message=message, cree_le=datetime(2026, 10, 20, tzinfo=UTC))
        return self.echos[message]

    async def trouver(self, message: str) -> Echo | None:
        return self.echos.get(message)


@pytest.fixture
def emetteur() -> EmetteurDeTest:
    return EmetteurDeTest()


@pytest.fixture
async def anonyme(emetteur: EmetteurDeTest) -> AsyncIterator[httpx.AsyncClient]:
    """Client sans jeton ; chaque test choisit l'appelant qu'il simule."""
    config = Parametres(database_url="postgresql+asyncpg://test@localhost/echo", instance=INSTANCE)
    app = creer_app(config, verificateur_jetons=emetteur.verificateur())
    depot = DepotEnMemoire()

    def depot_de_test() -> DepotEchos:
        return depot

    app.dependency_overrides[obtenir_depot] = depot_de_test
    # Sans lifespan : ni base ni Consul ne sont démarrés.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def client(anonyme: httpx.AsyncClient, emetteur: EmetteurDeTest) -> httpx.AsyncClient:
    """Compte de service autorisé à écrire (scope echos:write)."""
    anonyme.headers.update(emetteur.entetes(client="services", scopes=["echos:write"]))
    return anonyme


async def test_enregistrer_puis_relire_un_echo(client: httpx.AsyncClient) -> None:
    creation = await client.post("/api/v1/echos", json={"message": "bonjour"})
    lecture = await client.get("/api/v1/echos/bonjour")

    assert creation.status_code == 201
    assert lecture.status_code == 200
    assert lecture.json() == {
        "message": "bonjour",
        "instance": INSTANCE,
        "cree_le": "2026-10-20T00:00:00Z",
    }


async def test_echo_inconnu_renvoie_404_problem_details(client: httpx.AsyncClient) -> None:
    reponse = await client.get("/api/v1/echos/inconnu")

    assert reponse.status_code == 404
    assert reponse.headers["content-type"] == "application/problem+json"
    assert reponse.json()["code"] == "ECHO_INTROUVABLE"


async def test_echo_deja_existant_renvoie_409(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/echos", json={"message": "bonjour"})
    reponse = await client.post("/api/v1/echos", json={"message": "bonjour"})

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "ECHO_EXISTANT"


@pytest.mark.parametrize("corps", [{"message": ""}, {"message": "x" * 101}, {}])
async def test_corps_invalide_renvoie_422_problem_details(
    client: httpx.AsyncClient, corps: dict[str, str]
) -> None:
    reponse = await client.post("/api/v1/echos", json=corps)

    assert reponse.status_code == 422
    assert reponse.headers["content-type"] == "application/problem+json"
    probleme = reponse.json()
    assert probleme["code"] == "REQUETE_INVALIDE"
    assert probleme["erreurs"][0]["champ"].startswith("body")


async def test_sans_jeton_la_lecture_repond_401(anonyme: httpx.AsyncClient) -> None:
    reponse = await anonyme.get("/api/v1/echos/bonjour")

    assert reponse.status_code == 401
    assert reponse.headers["content-type"] == "application/problem+json"
    assert reponse.headers["WWW-Authenticate"].startswith("Bearer")
    assert reponse.json()["code"] == "JETON_ABSENT"


async def test_un_jeton_sans_le_scope_echos_write_recoit_403(
    anonyme: httpx.AsyncClient, emetteur: EmetteurDeTest
) -> None:
    client_sans_scope = emetteur.entetes(roles=["customer"], scopes=["openid", "profile"])

    reponse = await anonyme.post(
        "/api/v1/echos", json={"message": "bonjour"}, headers=client_sans_scope
    )

    assert reponse.status_code == 403
    assert reponse.headers["content-type"] == "application/problem+json"
    probleme = reponse.json()
    assert probleme["code"] == "SCOPE_MANQUANT"
    assert probleme["detail"] == "Scope requis : echos:write."
    # La lecture n'exige qu'un appelant authentifié.
    lecture = await anonyme.get("/api/v1/echos/bonjour", headers=client_sans_scope)
    assert lecture.status_code == 404


async def test_un_jeton_expire_recoit_401(
    anonyme: httpx.AsyncClient, emetteur: EmetteurDeTest
) -> None:
    reponse = await anonyme.get(
        "/api/v1/echos/bonjour", headers=emetteur.entetes(expire_dans=-3600)
    )

    assert reponse.status_code == 401
    assert reponse.json()["code"] == "JETON_EXPIRE"


async def test_un_jeton_d_une_autre_cle_recoit_401(anonyme: httpx.AsyncClient) -> None:
    pirate = EmetteurDeTest()  # même kid, autre clé privée

    reponse = await anonyme.get("/api/v1/echos/bonjour", headers=pirate.entetes())

    assert reponse.status_code == 401
    assert reponse.json()["code"] == "JETON_INVALIDE"


async def test_des_en_tetes_seuls_ne_suffisent_pas(
    anonyme: httpx.AsyncClient, emetteur: EmetteurDeTest
) -> None:
    usurpe = {"X-User-Id": "admin", "X-User-Roles": "admin"}
    sans_jeton = await anonyme.get("/api/v1/echos/bonjour", headers=usurpe)
    jeton_d_un_autre = await anonyme.get(
        "/api/v1/echos/bonjour", headers={**usurpe, **emetteur.entetes(sujet="client-42")}
    )

    assert sans_jeton.status_code == 401
    assert jeton_d_un_autre.status_code == 401
    assert jeton_d_un_autre.json()["code"] == "JETON_INVALIDE"
