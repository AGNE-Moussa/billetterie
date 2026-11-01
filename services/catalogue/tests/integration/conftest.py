"""Fixtures d'intégration du catalogue (plan docs/test-plans/BIL-004.md).

Vraie base PostgreSQL 16 par module de tests, migrée par `alembic upgrade head` avec
`services/catalogue/alembic.ini` ; jamais de simulacre de la base. L'application est appelée
par `httpx.ASGITransport` sous lifespan, jetons de `commun.faux_jetons.EmetteurDeTest`.

Toute lecture ou écriture directe en base passe par la fixture `base`, qui vérifie d'abord la
présence des tables du ticket : sans la migration, le test échoue par une assertion qui le dit,
pas par une erreur SQL.
"""

import os
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from catalogue.config import Parametres
from catalogue.principal import creer_app
from commun.faux_jetons import EmetteurDeTest

RACINE = Path(__file__).resolve().parents[4]
ALEMBIC_INI = RACINE / "services" / "catalogue" / "alembic.ini"
SCHEMA_SEANCE_PROGRAMMEE = RACINE / "docs" / "evenements" / "ticketing.show.scheduled.json"
CONTRAT = RACINE / "services" / "catalogue" / "openapi.yaml"
IMAGE_POSTGRES = "postgres:16.10-alpine"

TABLES_METIER = ("evenements", "lieux", "seances", "categories", "rangs")
TABLES_MESSAGERIE = ("outbox", "messages_traites")
TABLES_DU_TICKET = TABLES_METIER + TABLES_MESSAGERIE
# Délai d'un appel à l'application : une requête qui ne répond pas fait échouer le test.
DELAI_APPEL = 60.0
CONNEXION_BORNEE = {"timeout": 30, "command_timeout": 30}

EVENEMENT_COMMUN = {"nom": "Concert de test", "description": "Description synthétique"}
LIEU_COMMUN = {"nom": "Salle de test", "adresse": "1 rue de l'Exemple", "ville": "Villetest"}
CATEGORIES_COMMUNES = [
    {
        "nom": "Fosse",
        "prix": 4500,
        "rangs": [{"rang": "A", "nombre_places": 10}, {"rang": "B", "nombre_places": 12}],
    }
]


def migrer(database_url: str, cible: str = "head", sens: str = "upgrade") -> None:
    """`alembic upgrade|downgrade <cible>` avec le alembic.ini du service (appel bloquant)."""
    precedente = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        getattr(command, sens)(Config(str(ALEMBIC_INI)), cible)
    finally:
        if precedente is None:
            del os.environ["DATABASE_URL"]
        else:
            os.environ["DATABASE_URL"] = precedente


@pytest.fixture(scope="session")
def migration() -> Callable[..., None]:
    """La fonction `migrer`, pour les tests qui pilotent eux-mêmes Alembic."""
    return migrer


@pytest.fixture(scope="module")
def postgres() -> Iterator[PostgresContainer]:
    """PostgreSQL 16 jetable du module (utilisateur et base `catalogue`, mot de passe généré)."""
    mot_de_passe = secrets.token_urlsafe(16)
    with PostgresContainer(
        IMAGE_POSTGRES, username="catalogue", password=mot_de_passe, dbname="catalogue"
    ) as pg:
        pg.mot_de_passe = mot_de_passe  # type: ignore[attr-defined]
        yield pg


@pytest.fixture(scope="module")
def url_base(postgres: PostgresContainer) -> str:
    """URL de la base du module, non migrée."""
    # Sous Windows, « localhost » passe d'abord par IPv6 et Docker Desktop coupe la connexion.
    hote = postgres.get_container_host_ip().replace("localhost", "127.0.0.1")
    mot_de_passe = postgres.mot_de_passe  # type: ignore[attr-defined]
    port = postgres.get_exposed_port(5432)
    return f"postgresql+asyncpg://catalogue:{mot_de_passe}@{hote}:{port}/catalogue"


@pytest.fixture(scope="module")
def database_url(url_base: str) -> str:
    """Base du module migrée avec les vraies migrations du service."""
    migrer(url_base)
    return url_base


class Base:
    """Lectures et écritures directes en base, pour vérifier l'état après un appel d'API."""

    def __init__(self, database_url: str) -> None:
        self.url = database_url

    async def _executer(self, requete: str, parametres: dict[str, Any] | None = None) -> Any:
        moteur = create_async_engine(self.url, connect_args=CONNEXION_BORNEE)
        try:
            async with moteur.begin() as connexion:
                resultat = await connexion.execute(sa.text(requete), parametres or {})
                return list(resultat.mappings()) if resultat.returns_rows else []
        finally:
            await moteur.dispose()

    async def tables(self) -> set[str]:
        lignes = await self._executer(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        return {ligne["table_name"] for ligne in lignes}

    async def exiger_tables(self, *tables: str) -> None:
        attendues = set(tables or TABLES_DU_TICKET)
        presentes = await self.tables()
        assert attendues <= presentes, (
            f"tables absentes de la base migrée : {sorted(attendues - presentes)} "
            f"(présentes : {sorted(presentes)})"
        )

    async def lignes(self, requete: str, **parametres: Any) -> list[Any]:
        """SELECT direct ; les tables du ticket doivent exister."""
        await self.exiger_tables()
        return await self._executer(requete, parametres)  # type: ignore[no-any-return]

    async def executer(self, requete: str, **parametres: Any) -> None:
        """Écriture directe dans sa propre transaction ; les tables du ticket doivent exister."""
        await self.exiger_tables()
        await self._executer(requete, parametres)

    async def compter(self, table: str) -> int:
        assert table in TABLES_DU_TICKET, table
        await self.exiger_tables(table)
        lignes = await self._executer(f"SELECT count(*) AS n FROM {table}")  # noqa: S608
        return int(lignes[0]["n"])

    async def effectifs(self) -> dict[str, int]:
        return {table: await self.compter(table) for table in TABLES_DU_TICKET}

    async def outbox(self) -> list[Any]:
        return await self.lignes("SELECT * FROM outbox ORDER BY cree_le, id")

    async def vider(self) -> None:
        """Vide les tables du ticket déjà créées (aucune tant que la migration manque)."""
        presentes = await self.tables()
        a_vider = [table for table in TABLES_DU_TICKET if table in presentes]
        if a_vider:
            await self._executer(f"TRUNCATE {', '.join(a_vider)} CASCADE")


@pytest.fixture
async def base(database_url: str) -> AsyncIterator[Base]:
    """Accès direct à la base ; chaque cas part de tables vides."""
    acces = Base(database_url)
    await acces.vider()
    yield acces


class Jetons:
    """En-têtes Authorization des appelants du plan (données synthétiques communes)."""

    def __init__(self, emetteur: EmetteurDeTest) -> None:
        self.admin = emetteur.entetes(
            sujet="admin-test", roles=["admin"], scopes=["events:read", "events:write"]
        )
        self.client = emetteur.entetes(
            sujet="client-test", roles=["customer"], scopes=["events:read"]
        )
        self.revendeur = emetteur.entetes(
            sujet="revendeur-test", roles=["partner"], scopes=["events:read"], client="revendeur"
        )
        self.service = emetteur.entetes(
            sujet="service-test", client="services", scopes=["seats:lock"]
        )


@pytest.fixture
def emetteur() -> EmetteurDeTest:
    return EmetteurDeTest()


@pytest.fixture
def jetons(emetteur: EmetteurDeTest) -> Jetons:
    return Jetons(emetteur)


def parametres_catalogue(database_url: str, **reglages: Any) -> Parametres:
    reglages.setdefault("instance", "catalogue-test")
    reglages.setdefault("consul_actif", False)
    return Parametres(database_url=database_url, **reglages)


@pytest.fixture
async def app(database_url: str, emetteur: EmetteurDeTest, base: Base) -> AsyncIterator[FastAPI]:
    """Application sur la base migrée, lifespan démarré, sans Consul ni RabbitMQ."""
    application = creer_app(
        parametres_catalogue(database_url), verificateur_jetons=emetteur.verificateur()
    )
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client_public(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Client sans jeton."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=DELAI_APPEL
    ) as client:
        yield client


@pytest.fixture
async def client_admin(app: FastAPI, jetons: Jetons) -> AsyncIterator[httpx.AsyncClient]:
    """Client avec le jeton admin (scope events:write)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=jetons.admin, timeout=DELAI_APPEL
    ) as client:
        yield client


def instant(jours: float = 0, **decalage: float) -> datetime:
    """Maintenant (UTC, à la seconde) + `jours` : dates de séance avec fuseau."""
    maintenant = datetime.now(UTC).replace(microsecond=0)
    return maintenant + timedelta(days=jours, **decalage)


class Catalogue:
    """Création des données communes par l'API, avec le jeton admin.

    Chaque création exige 201 : tant que la route n'est pas implémentée, le test échoue sur
    cette assertion, en donnant le statut et le corps reçus.
    """

    EVENEMENT = EVENEMENT_COMMUN
    LIEU = LIEU_COMMUN
    CATEGORIES = CATEGORIES_COMMUNES

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    @staticmethod
    def instant(jours: float = 0, **decalage: float) -> datetime:
        return instant(jours, **decalage)

    @staticmethod
    def corps_seance(
        lieu_id: str, debut: datetime | str | None = None, categories: Any = None
    ) -> dict[str, Any]:
        moment = debut if debut is not None else instant(30)
        return {
            "lieu_id": lieu_id,
            "debut": moment.isoformat() if isinstance(moment, datetime) else moment,
            "categories": CATEGORIES_COMMUNES if categories is None else categories,
        }

    async def _creer(self, chemin: str, corps: dict[str, Any], **options: Any) -> dict[str, Any]:
        reponse = await self.client.post(chemin, json=corps, **options)
        assert reponse.status_code == 201, (
            f"POST {chemin} : {reponse.status_code} au lieu de 201 : {reponse.text}"
        )
        resultat: dict[str, Any] = reponse.json()
        return resultat

    async def evenement(self, **champs: str) -> dict[str, Any]:
        return await self._creer("/api/v1/events", {**EVENEMENT_COMMUN, **champs})

    async def lieu(self, **champs: str) -> dict[str, Any]:
        return await self._creer("/api/v1/venues", {**LIEU_COMMUN, **champs})

    async def seance(
        self,
        evenement_id: str,
        lieu_id: str,
        debut: datetime | None = None,
        categories: Any = None,
        **options: Any,
    ) -> dict[str, Any]:
        return await self._creer(
            f"/api/v1/events/{evenement_id}/shows",
            self.corps_seance(lieu_id, debut, categories),
            **options,
        )


@pytest.fixture
def catalogue(client_admin: httpx.AsyncClient) -> Catalogue:
    return Catalogue(client_admin)


async def borne[T](etape: str, attente: Awaitable[T], delai: float = DELAI_APPEL) -> T:
    """Attend `attente` au plus `delai` secondes, sinon AssertionError qui nomme l'étape."""
    debut = time.monotonic()
    with anyio.move_on_after(delai):
        return await attente
    raise AssertionError(
        f"{etape} : pas de réponse en {delai:.0f} s ({time.monotonic() - debut:.0f} s mesurées)"
    )


@pytest.fixture
def borner() -> Any:
    return borne
