"""Routes du service echo, sans base : le dépôt est remplacé par un dépôt en mémoire."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest

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
async def client() -> AsyncIterator[httpx.AsyncClient]:
    config = Parametres(database_url="postgresql+asyncpg://test@localhost/echo", instance=INSTANCE)
    app = creer_app(config)
    depot = DepotEnMemoire()

    def depot_de_test() -> DepotEchos:
        return depot

    app.dependency_overrides[obtenir_depot] = depot_de_test
    # Sans lifespan : ni base ni Consul ne sont démarrés.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


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
