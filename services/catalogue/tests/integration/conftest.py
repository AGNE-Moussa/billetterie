"""Fixtures d'intégration du catalogue (plan docs/test-plans/BIL-004.md).

Vraie base PostgreSQL 16 par module de tests, migrée par `alembic upgrade head` avec
`services/catalogue/alembic.ini` ; jamais de simulacre de la base. L'application est appelée
par `httpx.ASGITransport` sous lifespan, jetons de `commun.faux_jetons.EmetteurDeTest`.

Toute lecture ou écriture directe en base passe par la fixture `base`, qui vérifie d'abord la
présence des tables du ticket : sans la migration, le test échoue par une assertion qui le dit,
pas par une erreur SQL.

BIL-005 (plan docs/test-plans/BIL-005.md) : conteneur Redis par module (`redis`), observateur
`cache_redis` (SCAN du seul préfixe `catalogue:cache:`, Redis vidé à chaque cas), fabrique
`plateforme_cache` (application avec `redis_url` et durées courtes), pause Docker `en_pause`.
"""

import os
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager, contextmanager
from dataclasses import dataclass
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
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

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


# --- Cache Redis (plan docs/test-plans/BIL-005.md) -------------------------------------------

IMAGE_REDIS = "redis:7.4.6-alpine"  # même image que le service redis de compose.yaml
# Seul nom de clé connu des tests (Q10) : le reste du format est interne au service.
PREFIXE_CACHE = "catalogue:cache:"
# Durées de test (Q4, Q8) : fraîcheur 1 s, delai_base 1 s. Le secours dure 20 s par défaut
# pour qu'une lecture faite pendant la pause (jusqu'à delai_base + 5 s chacune) le trouve
# encore ; le cas d'expiration du secours règle lui-même 5 s.
REGLAGES_CACHE_TEST: dict[str, Any] = {
    "cache_duree_fraiche": 1.0,
    "cache_duree_secours": 20.0,
    "delai_base": 1.0,
}
# Attente qui dépasse la fraîcheur de test : la copie fraîche a expiré, le secours reste.
ATTENTE_FRAICHEUR_EXPIREE = 1.5


@pytest.fixture(scope="module")
def redis() -> Iterator[DockerContainer]:
    """Redis 7 jetable du module, sans mot de passe comme celui de compose.yaml."""
    conteneur = (
        DockerContainer(IMAGE_REDIS)
        .with_exposed_ports(6379)
        .waiting_for(LogMessageWaitStrategy("Ready to accept connections"))
    )
    with conteneur:
        yield conteneur


@pytest.fixture(scope="module")
def redis_url(redis: DockerContainer) -> str:
    # Sous Windows, « localhost » passe d'abord par IPv6 et Docker Desktop coupe la connexion.
    hote = redis.get_container_host_ip().replace("localhost", "127.0.0.1")
    return f"redis://{hote}:{redis.get_exposed_port(6379)}/0"


class ObservateurRedis:
    """Lecture directe de Redis par les tests : clés du préfixe `catalogue:cache:` (SCAN)."""

    prefixe = PREFIXE_CACHE

    def __init__(self, url: str) -> None:
        self.url = url

    def _client(self) -> Redis:
        return Redis.from_url(self.url, decode_responses=True, socket_timeout=10)

    async def vider(self) -> None:
        """FLUSHDB : copies et compteurs internes repartent de zéro (comme la base vidée)."""
        async with self._client() as client:
            await client.flushdb()

    async def cles(self) -> list[str]:
        async with self._client() as client:
            return sorted([cle async for cle in client.scan_iter(match=f"{PREFIXE_CACHE}*")])

    async def expirations_ms(self) -> dict[str, int]:
        """PTTL de chaque clé du préfixe (-1 : sans expiration, -2 : disparue entre-temps)."""
        async with self._client() as client:
            cles = [cle async for cle in client.scan_iter(match=f"{PREFIXE_CACHE}*")]
            return {cle: int(await client.pttl(cle)) for cle in cles}

    async def valeurs(self) -> dict[str, Any]:
        async with self._client() as client:
            cles = [cle async for cle in client.scan_iter(match=f"{PREFIXE_CACHE}*")]
            return {cle: await client.get(cle) for cle in cles}

    async def exiger_rempli(self, etape: str) -> list[str]:
        """Témoin : le cache a gardé au moins une copie, sinon le test ne prouverait rien."""
        cles = await self.cles()
        assert cles, f"{etape} : aucune clé {PREFIXE_CACHE}* dans Redis, le cache n'a rien gardé"
        return cles


@pytest.fixture
async def cache_redis(redis_url: str) -> ObservateurRedis:
    """Observateur de Redis ; chaque cas part d'un Redis vide."""
    observateur = ObservateurRedis(redis_url)
    await observateur.vider()
    return observateur


@dataclass
class PlateformeCache:
    """Application avec cache Redis, lifespan démarré, et ses clients."""

    app: FastAPI
    public: httpx.AsyncClient
    admin: httpx.AsyncClient
    catalogue: Catalogue
    reglages: dict[str, Any]

    @property
    def delai_lecture(self) -> float:
        """Borne d'une réponse pendant une panne : delai_base + 5 s (Q8)."""
        return float(self.reglages["delai_base"]) + 5.0

    async def semer_lectures(self) -> dict[str, str]:
        """Un événement, un lieu (Villetest), une séance ; chemin de chacune des 7 lectures."""
        evenement = str((await self.catalogue.evenement())["id"])
        lieu = str((await self.catalogue.lieu())["id"])
        seance = str((await self.catalogue.seance(evenement, lieu))["id"])
        return {
            "listerEvenements": "/api/v1/events",
            "lireEvenement": f"/api/v1/events/{evenement}",
            "listerSeances": f"/api/v1/events/{evenement}/shows",
            "lireSeance": f"/api/v1/events/{evenement}/shows/{seance}",
            "lireSeanceParId": f"/api/v1/shows/{seance}",
            "listerLieux": "/api/v1/venues",
            "lireLieu": f"/api/v1/venues/{lieu}",
        }


@pytest.fixture
def plateforme_cache(
    database_url: str,
    redis_url: str,
    emetteur: EmetteurDeTest,
    jetons: Jetons,
    base: Base,
    cache_redis: ObservateurRedis,
) -> Callable[..., AbstractAsyncContextManager[PlateformeCache]]:
    """Fabrique : `async with plateforme_cache(**reglages) as p` (durées de test par défaut)."""

    @asynccontextmanager
    async def demarrer(**reglages: Any) -> AsyncIterator[PlateformeCache]:
        complets = {**REGLAGES_CACHE_TEST, "redis_url": redis_url, **reglages}
        application = creer_app(
            parametres_catalogue(database_url, **complets),
            verificateur_jetons=emetteur.verificateur(),
        )
        transport = httpx.ASGITransport(app=application)
        async with (
            application.router.lifespan_context(application),
            httpx.AsyncClient(
                transport=transport, base_url="http://test", timeout=DELAI_APPEL
            ) as public,
            httpx.AsyncClient(
                transport=transport,
                base_url="http://test",
                headers=jetons.admin,
                timeout=DELAI_APPEL,
            ) as admin,
        ):
            yield PlateformeCache(application, public, admin, Catalogue(admin), complets)

    return demarrer


@pytest.fixture
async def plateforme(
    plateforme_cache: Callable[..., AbstractAsyncContextManager[PlateformeCache]],
) -> AsyncIterator[PlateformeCache]:
    """Application avec cache, durées de test par défaut."""
    async with plateforme_cache() as demarree:
        yield demarree


@contextmanager
def _en_pause(*conteneurs: DockerContainer) -> Iterator[None]:
    """`docker pause` des conteneurs, puis `unpause` quoi qu'il arrive."""
    en_pause: list[Any] = []
    try:
        for conteneur in conteneurs:
            enveloppe = conteneur.get_wrapped_container()
            enveloppe.pause()
            en_pause.append(enveloppe)
        yield
    finally:
        for enveloppe in en_pause:
            enveloppe.unpause()


@pytest.fixture
def en_pause() -> Any:
    return _en_pause


@pytest.fixture
def attente_fraicheur() -> float:
    return ATTENTE_FRAICHEUR_EXPIREE
