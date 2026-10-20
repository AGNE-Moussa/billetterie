"""Service echo sur une vraie base PostgreSQL : migrations Alembic, écriture, lecture, santé,
evénements dans l'outbox."""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer

from commun.faux_jetons import EmetteurDeTest
from commun.outbox import OUTBOX
from echo.config import Parametres
from echo.infra.base import creer_moteur
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
    emetteur = EmetteurDeTest()
    app = creer_app(
        Parametres(database_url=database_url, instance="echo-test", consul_actif=False),
        verificateur_jetons=emetteur.verificateur(),
    )
    jeton = emetteur.entetes(client="services", scopes=["echos:write"])
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", headers=jeton
        ) as client:
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


async def _outbox(database_url: str, message: str) -> list[sa.RowMapping]:
    """Lignes de l'outbox pour un message, lues directement en base."""
    moteur = creer_moteur(database_url)
    async with moteur.connect() as connexion:
        requete = sa.select(OUTBOX).where(OUTBOX.c.data["message"].astext == message)
        lignes = list((await connexion.execute(requete)).mappings())
    await moteur.dispose()
    return lignes


async def test_un_echo_enregistre_publie_son_evenement_par_l_outbox(
    client: httpx.AsyncClient, database_url: str
) -> None:
    await client.post(
        "/api/v1/echos", json={"message": "evenement"}, headers={"X-Correlation-Id": "requete-echo"}
    )

    lignes = await _outbox(database_url, "evenement")
    assert len(lignes) == 1
    assert lignes[0]["type"] == "ticketing.echo.created"
    assert lignes[0]["correlation_id"] == "requete-echo"
    # Pas de RabbitMQ dans ce test : l'événement attend le relais.
    assert lignes[0]["envoye_le"] is None


async def test_un_echo_refuse_ne_publie_aucun_evenement(
    client: httpx.AsyncClient, database_url: str
) -> None:
    await client.post("/api/v1/echos", json={"message": "double"})
    reponse = await client.post("/api/v1/echos", json={"message": "double"})

    assert reponse.status_code == 409
    assert len(await _outbox(database_url, "double")) == 1  # seul le premier
