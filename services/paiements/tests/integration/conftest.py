"""Fixtures d'intégration de paiements (plan docs/test-plans/BIL-008.md).

Vraie base PostgreSQL 16 par module, migrée par `alembic upgrade head` avec
`services/paiements/alembic.ini` ; jamais de simulacre de la base. L'application est appelée
par `httpx.ASGITransport` sous lifespan, avec le jeton du client `services` (scope
`payments:write`) fabriqué par `commun.faux_jetons.EmetteurDeTest`.
"""

import os
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

from commun.faux_jetons import EmetteurDeTest
from paiements.config import Parametres
from paiements.principal import creer_app

RACINE = Path(__file__).resolve().parents[4]
ALEMBIC_INI = RACINE / "services" / "paiements" / "alembic.ini"
IMAGE_POSTGRES = "postgres:16.10-alpine"
CONNEXION_BORNEE = {"timeout": 30, "command_timeout": 30}
DELAI_APPEL = 60.0
ROUTE_PAIEMENTS = "/api/v1/payments"
TABLES = ("paiements", "seances_annulees", "outbox", "messages_traites")

CARTE_ACCEPTEE = "4242424242424242"
CARTE_REFUSEE = "4000000000000002"


def migrer(database_url: str, cible: str = "head", sens: str = "upgrade") -> None:
    precedente = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        getattr(command, sens)(Config(str(ALEMBIC_INI)), cible)
    finally:
        if precedente is None:
            del os.environ["DATABASE_URL"]
        else:
            os.environ["DATABASE_URL"] = precedente


@pytest.fixture(scope="module")
def postgres() -> Iterator[PostgresContainer]:
    mot_de_passe = secrets.token_urlsafe(16)
    with PostgresContainer(
        IMAGE_POSTGRES, username="paiements", password=mot_de_passe, dbname="paiements"
    ) as pg:
        pg.mot_de_passe = mot_de_passe  # type: ignore[attr-defined]
        yield pg


@pytest.fixture(scope="module")
def url_base(postgres: PostgresContainer) -> str:
    # Sous Windows, « localhost » passe d'abord par IPv6 et Docker Desktop coupe la connexion.
    hote = postgres.get_container_host_ip().replace("localhost", "127.0.0.1")
    mot_de_passe = postgres.mot_de_passe  # type: ignore[attr-defined]
    port = postgres.get_exposed_port(5432)
    return f"postgresql+asyncpg://paiements:{mot_de_passe}@{hote}:{port}/paiements"


@pytest.fixture(scope="module")
def database_url(url_base: str) -> str:
    migrer(url_base)
    return url_base


class Base:
    def __init__(self, database_url: str) -> None:
        self.url = database_url

    async def _executer(self, requete: str, parametres: dict[str, Any]) -> list[dict[str, Any]]:
        moteur = create_async_engine(self.url, poolclass=NullPool, connect_args=CONNEXION_BORNEE)
        try:
            async with moteur.begin() as connexion:
                resultat = await connexion.execute(sa.text(requete), parametres)
                return (
                    [dict(ligne) for ligne in resultat.mappings()] if resultat.returns_rows else []
                )
        finally:
            await moteur.dispose()

    async def lignes(self, requete: str, **parametres: Any) -> list[dict[str, Any]]:
        return await self._executer(requete, parametres)

    async def executer(self, requete: str, **parametres: Any) -> None:
        await self._executer(requete, parametres)

    async def paiements(self) -> list[dict[str, Any]]:
        return await self._executer("SELECT * FROM paiements", {})

    async def annuler(self, seance_id: uuid.UUID) -> None:
        await self._executer(
            "INSERT INTO seances_annulees (seance_id, annulee_le) VALUES (:id, :le)",
            {"id": seance_id, "le": datetime.now(UTC)},
        )

    async def vider(self) -> None:
        await self._executer(f"TRUNCATE {', '.join(TABLES)} CASCADE", {})


@pytest.fixture
async def base(database_url: str) -> Base:
    acces = Base(database_url)
    await acces.vider()
    return acces


@dataclass
class Service:
    client: httpx.AsyncClient

    async def payer(
        self,
        *,
        commande_id: uuid.UUID,
        seance_id: uuid.UUID,
        montant: int = 4500,
        carte: str = CARTE_ACCEPTEE,
        cle: str | None = None,
    ) -> httpx.Response:
        corps = {
            "commande_id": str(commande_id),
            "seance_id": str(seance_id),
            "montant": montant,
            "carte_test": carte,
        }
        entetes = {"Idempotency-Key": cle if cle is not None else str(commande_id)}
        return await borne(
            f"POST {ROUTE_PAIEMENTS}",
            self.client.post(ROUTE_PAIEMENTS, json=corps, headers=entetes),
        )


@pytest.fixture
def service_paiements(
    database_url: str, base: Base
) -> Callable[..., AbstractAsyncContextManager[Service]]:
    """Fabrique : `async with service_paiements(**reglages) as service`."""

    @asynccontextmanager
    async def demarrer(**reglages: Any) -> AsyncIterator[Service]:
        emetteur = EmetteurDeTest()
        app = creer_app(
            Parametres(
                database_url=database_url,
                instance="paiements-test",
                consul_actif=False,
                **reglages,
            ),
            verificateur_jetons=emetteur.verificateur(),
        )
        entetes = emetteur.entetes(
            sujet="service-account-services", client="services", scopes=["payments:write"]
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers=entetes,
                timeout=DELAI_APPEL,
            ) as client,
        ):
            yield Service(client)

    return demarrer


@pytest.fixture
async def service(
    service_paiements: Callable[..., AbstractAsyncContextManager[Service]],
) -> AsyncIterator[Service]:
    async with service_paiements() as demarre:
        yield demarre


def exiger_statut(reponse: httpx.Response, attendu: int, etape: str) -> dict[str, Any]:
    assert reponse.status_code == attendu, (
        f"{etape} : {reponse.status_code} au lieu de {attendu} : {reponse.text}"
    )
    corps: dict[str, Any] = reponse.json()
    return corps


def exiger_probleme(reponse: httpx.Response, statut: int, code: str, etape: str) -> dict[str, Any]:
    corps = exiger_statut(reponse, statut, etape)
    assert reponse.headers["content-type"].startswith("application/problem+json"), etape
    assert corps.get("code") == code, f"{etape} : {corps}"
    return corps


async def borne[T](etape: str, attente: Awaitable[T], delai: float = DELAI_APPEL) -> T:
    debut = time.monotonic()
    with anyio.move_on_after(delai):
        return await attente
    raise AssertionError(
        f"{etape} : pas de réponse en {delai:.0f} s ({time.monotonic() - debut:.0f} s mesurées)"
    )


@dataclass(frozen=True)
class Outils:
    carte_acceptee: str = CARTE_ACCEPTEE
    carte_refusee: str = CARTE_REFUSEE
    exiger_statut: Callable[..., dict[str, Any]] = exiger_statut
    exiger_probleme: Callable[..., dict[str, Any]] = exiger_probleme
    borne: Callable[..., Any] = borne
    migrer: Callable[..., None] = field(default=migrer)


@pytest.fixture(scope="session")
def outils() -> Outils:
    return Outils()
