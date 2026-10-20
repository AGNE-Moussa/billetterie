"""Service echo sur une vraie base PostgreSQL : migrations Alembic, écriture, lecture, santé."""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer

from echo.config import Parametres
from echo.principal import creer_app

pytestmark = pytest.mark.anyio

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    """Base jetable, migrée avec les vraies migrations du service."""
    with PostgresContainer(
        "postgres:16.10-alpine", username="echo", password="echo", dbname="echo"
    ) as pg:
        # Sous Windows, « localhost » passe d'abord par IPv6 et Docker Desktop coupe la connexion.
        hote = pg.get_container_host_ip().replace("localhost", "127.0.0.1")
        url = f"postgresql+asyncpg://echo:echo@{hote}:{pg.get_exposed_port(5432)}/echo"
        precedente = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        try:
            command.upgrade(Config(str(ALEMBIC_INI)), "head")
        finally:
            if precedente is None:
                del os.environ["DATABASE_URL"]
            else:
                os.environ["DATABASE_URL"] = precedente
        yield url


@pytest.fixture
async def client(database_url: str) -> AsyncIterator[httpx.AsyncClient]:
    app = creer_app(Parametres(database_url=database_url, instance="echo-test", consul_actif=False))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_sante_verifie_la_base(client: httpx.AsyncClient) -> None:
    reponse = await client.get("/health")

    assert reponse.status_code == 200
    assert reponse.json() == {"statut": "ok"}


async def test_echo_enregistre_est_relu_depuis_la_base(client: httpx.AsyncClient) -> None:
    creation = await client.post("/api/v1/echos", json={"message": "persistant"})
    lecture = await client.get("/api/v1/echos/persistant")

    assert creation.status_code == 201
    assert lecture.status_code == 200
    assert lecture.json()["cree_le"] == creation.json()["cree_le"]


async def test_contrainte_unique_renvoie_409(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/echos", json={"message": "unique"})
    reponse = await client.post("/api/v1/echos", json={"message": "unique"})

    assert reponse.status_code == 409
    assert reponse.json()["code"] == "ECHO_EXISTANT"


async def test_echo_absent_de_la_base_renvoie_404(client: httpx.AsyncClient) -> None:
    reponse = await client.get("/api/v1/echos/jamais-enregistre")

    assert reponse.status_code == 404
