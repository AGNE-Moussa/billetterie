"""Liste paginée des echos (`GET /api/v1/echos`) sur une vraie base PostgreSQL migrée par
Alembic : pagination, tri par `cree_le` décroissant, page au-delà de la fin (BIL-F25)."""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer

from commun.faux_jetons import EmetteurDeTest
from echo.config import Parametres
from echo.infra.base import EchoLigne, creer_moteur
from echo.principal import creer_app

pytestmark = pytest.mark.anyio

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    """Base jetable dédiée à ce fichier, migrée avec les vraies migrations du service."""
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


@pytest.fixture(autouse=True)
async def base_vide(database_url: str) -> None:
    """Chaque cas part d'une table des echos vide."""
    moteur = creer_moteur(database_url)
    async with moteur.begin() as connexion:
        await connexion.execute(sa.delete(EchoLigne))
    await moteur.dispose()


@pytest.fixture
async def client(database_url: str, base_vide: None) -> AsyncIterator[httpx.AsyncClient]:
    emetteur = EmetteurDeTest()
    app = creer_app(
        Parametres(database_url=database_url, instance="echo-test", consul_actif=False),
        verificateur_jetons=emetteur.verificateur(),
    )
    jeton = emetteur.entetes(client="services", scopes=["echos:write", "echos:read"])
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", headers=jeton
        ) as client:
            yield client


async def _creer(client: httpx.AsyncClient, message: str) -> dict[str, Any]:
    reponse = await client.post("/api/v1/echos", json={"message": message})
    assert reponse.status_code == 201, reponse.text
    corps: dict[str, Any] = reponse.json()
    return corps


async def _page(client: httpx.AsyncClient, **parametres: int) -> dict[str, Any]:
    reponse = await client.get("/api/v1/echos", params=parametres)
    assert reponse.status_code == 200, reponse.text
    corps: dict[str, Any] = reponse.json()
    return corps


def _messages(page: dict[str, Any]) -> list[str]:
    return [element["message"] for element in page["elements"]]


# D3


async def test_les_pages_successives_sur_la_base_ne_repetent_ni_ne_perdent_aucun_echo(
    client: httpx.AsyncClient,
) -> None:
    attendus = [f"message-test-{i:02d}" for i in range(1, 8)]
    for message in attendus:
        await _creer(client, message)

    pages = [await _page(client, page=numero, size=3) for numero in (1, 2, 3)]

    assert [len(page["elements"]) for page in pages] == [3, 3, 1]
    assert [page["total"] for page in pages] == [7, 7, 7]
    lus = [message for page in pages for message in _messages(page)]
    assert len(lus) == len(set(lus))
    assert set(lus) == set(attendus)


# D4


async def test_la_liste_relue_en_base_renvoie_le_cree_le_de_la_creation(
    client: httpx.AsyncClient,
) -> None:
    creation = await _creer(client, "message-test-01")

    page = await _page(client)

    assert len(page["elements"]) == 1
    element = page["elements"][0]
    assert element["message"] == "message-test-01"
    assert element["instance"] == "echo-test"
    assert datetime.fromisoformat(element["cree_le"]) == datetime.fromisoformat(creation["cree_le"])


# D5


async def test_la_base_renvoie_les_echos_du_plus_recent_au_plus_ancien(
    client: httpx.AsyncClient,
) -> None:
    for message in ("message-test-01", "message-test-02", "message-test-03"):
        await _creer(client, message)

    page = await _page(client)

    assert _messages(page) == ["message-test-03", "message-test-02", "message-test-01"]
    dates = [datetime.fromisoformat(element["cree_le"]) for element in page["elements"]]
    assert dates[0] > dates[1] > dates[2]


async def test_des_echos_crees_au_meme_instant_gardent_un_ordre_stable(
    client: httpx.AsyncClient,
) -> None:
    attendus = [f"message-test-{i:02d}" for i in range(1, 11)]
    await asyncio.gather(*(_creer(client, message) for message in attendus))

    premiere = _messages(await _page(client, size=100))
    seconde = _messages(await _page(client, size=100))
    par_pages = [
        message
        for numero in (1, 2, 3, 4)
        for message in _messages(await _page(client, page=numero, size=3))
    ]

    assert sorted(premiere) == attendus
    assert seconde == premiere
    assert par_pages == premiere


# D6


async def test_une_page_au_dela_de_la_fin_sur_la_base_renvoie_une_liste_vide(
    client: httpx.AsyncClient,
) -> None:
    await _creer(client, "message-test-01")
    await _creer(client, "message-test-02")

    reponse = await client.get("/api/v1/echos", params={"page": 2, "size": 2})

    assert reponse.status_code == 200
    assert reponse.json()["elements"] == []
    assert reponse.json()["total"] == 2
