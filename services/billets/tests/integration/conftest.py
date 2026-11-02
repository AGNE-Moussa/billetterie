"""Fixtures d'intégration de billets (plan docs/test-plans/BIL-006.md).

Vraie base PostgreSQL 16 par module de tests, migrée par `alembic upgrade head` avec
`services/billets/alembic.ini`, vrai Redis 7 (même image que compose.yaml) ; jamais de
simulacre de la base ni de Redis. L'application est appelée par `httpx.ASGITransport` sous
lifespan ; jetons de `commun.faux_jetons.EmetteurDeTest`.

Deux instances (`instance_1`, `instance_2`) partagent la même base et le même Redis, comme
`billets-1` et `billets-2` (fixtures du plan, décision Q24).

Les places d'une séance sont écrites directement dans la table `places` (données synthétiques
communes du plan : Fosse A×10 et B×12, Balcon C×5, 27 places) : la création par le consommateur
`ticketing.show.scheduled` est couverte à part (E5).
"""

import os
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
import sqlalchemy as sa
import yaml
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from jsonschema import Draft202012Validator
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from billets.config import Parametres
from billets.principal import creer_app
from commun.faux_jetons import EmetteurDeTest

RACINE = Path(__file__).resolve().parents[4]
ALEMBIC_INI = RACINE / "services" / "billets" / "alembic.ini"
CONTRAT = RACINE / "services" / "billets" / "openapi.yaml"
IMAGE_POSTGRES = "postgres:16.10-alpine"
IMAGE_REDIS = "redis:7.4.6-alpine"  # même image que le service redis de compose.yaml

TABLES_METIER = ("places", "billets")
TABLES_MESSAGERIE = ("outbox", "messages_traites")
TABLES_DU_TICKET = TABLES_METIER + TABLES_MESSAGERIE
# Délai d'un appel à l'application : une requête qui ne répond pas fait échouer le test.
DELAI_APPEL = 60.0
CONNEXION_BORNEE = {"timeout": 30, "command_timeout": 30}

ROUTE_PLACES = "/api/v1/seats"
# Durées par défaut (décision Q8) et durées courtes des cas d'expiration (plan).
DUREE_RESERVATION = 600
DUREE_CONFIRMATION = 3600
DUREES_COURTES: dict[str, Any] = {"duree_verrou_reservation": 2, "duree_verrou_confirmation": 4}
# Tolérance sur expire_le (décision Q16).
TOLERANCE_EXPIRATION = timedelta(seconds=2)

# Séance commune du plan : (catégorie, prix en centimes, [(rang, nombre de places)]).
CATEGORIES_COMMUNES = (
    ("Fosse", 4500, (("A", 10), ("B", 12))),
    ("Balcon", 3000, (("C", 5),)),
)
NOMBRE_PLACES = 27


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
    """PostgreSQL 16 jetable du module (utilisateur et base `billets`, mot de passe généré)."""
    mot_de_passe = secrets.token_urlsafe(16)
    with PostgresContainer(
        IMAGE_POSTGRES, username="billets", password=mot_de_passe, dbname="billets"
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
    return f"postgresql+asyncpg://billets:{mot_de_passe}@{hote}:{port}/billets"


@pytest.fixture(scope="module")
def database_url(url_base: str) -> str:
    """Base du module migrée avec les vraies migrations du service."""
    migrer(url_base)
    return url_base


# --- Accès direct à la base -------------------------------------------------------------------


@dataclass(frozen=True)
class Seance:
    """Séance semée en base : `places["A1"]` est l'identifiant de la place A1."""

    id: uuid.UUID
    categories: dict[str, uuid.UUID]
    places: dict[str, uuid.UUID]
    categorie_de: dict[str, uuid.UUID] = field(default_factory=dict)

    def ordre(self) -> list[str]:
        """Libellés des places par rang, puis numéro (A1…A10, B1…B12, C1…C5)."""
        return [
            f"{rang}{numero}"
            for _, _, rangs in CATEGORIES_COMMUNES
            for rang, nombre in rangs
            for numero in range(1, nombre + 1)
        ]


class Base:
    """Lectures et écritures directes en base, pour préparer et vérifier l'état."""

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
        await self.exiger_tables()
        return await self._executer(requete, parametres)  # type: ignore[no-any-return]

    async def executer(self, requete: str, **parametres: Any) -> None:
        await self.exiger_tables()
        await self._executer(requete, parametres)

    async def compter(self, table: str, condition: str = "", **parametres: Any) -> int:
        assert table in TABLES_DU_TICKET, table
        await self.exiger_tables(table)
        requete = f"SELECT count(*) AS n FROM {table}"  # noqa: S608 : table de la liste
        if condition:
            requete += f" WHERE {condition}"
        lignes = await self._executer(requete, parametres)
        return int(lignes[0]["n"])

    async def vider(self) -> None:
        presentes = await self.tables()
        a_vider = [table for table in TABLES_DU_TICKET if table in presentes]
        if a_vider:
            await self._executer(f"TRUNCATE {', '.join(a_vider)} CASCADE")

    async def semer_seance(self) -> Seance:
        """Séance commune du plan : 27 places, insérées dans le désordre des rangs (B, A, C)."""
        await self.exiger_tables("places")
        seance_id = uuid.uuid4()
        categories: dict[str, uuid.UUID] = {}
        places: dict[str, uuid.UUID] = {}
        categorie_de: dict[str, uuid.UUID] = {}
        a_inserer: list[dict[str, Any]] = []
        for nom, _prix, rangs in CATEGORIES_COMMUNES:
            categorie_id = uuid.uuid4()
            categories[nom] = categorie_id
            for rang, nombre in rangs:
                for numero in range(1, nombre + 1):
                    place_id = uuid.uuid4()
                    places[f"{rang}{numero}"] = place_id
                    categorie_de[f"{rang}{numero}"] = categorie_id
                    a_inserer.append(
                        {
                            "id": place_id,
                            "seance_id": seance_id,
                            "rang": rang,
                            "numero": numero,
                            "categorie_id": categorie_id,
                        }
                    )
        # Rangs dans le désordre : l'ordre de la réponse ne doit rien à celui de l'insertion.
        a_inserer.sort(
            key=lambda ligne: ({"B": 0, "A": 1, "C": 2}[ligne["rang"]], -ligne["numero"])
        )
        moteur = create_async_engine(self.url, connect_args=CONNEXION_BORNEE)
        try:
            async with moteur.begin() as connexion:
                await connexion.execute(
                    sa.text(
                        "INSERT INTO places (id, seance_id, rang, numero, categorie_id)"
                        " VALUES (:id, :seance_id, :rang, :numero, :categorie_id)"
                    ),
                    a_inserer,
                )
        finally:
            await moteur.dispose()
        return Seance(seance_id, categories, places, categorie_de)

    async def inserer_billet(
        self, seance_id: uuid.UUID, place_id: uuid.UUID, statut: str = "EMIS"
    ) -> uuid.UUID:
        """Billet synthétique (colonnes de docs/modele-donnees.md, migration 0003)."""
        billet_id = uuid.uuid4()
        await self.executer(
            "INSERT INTO billets (id, commande_id, client, seance_id, place_id, statut, qr_code,"
            " emis_le) VALUES (:id, :commande_id, :client, :seance_id, :place_id, :statut,"
            " :qr_code, :emis_le)",
            id=billet_id,
            commande_id=uuid.uuid4(),
            client="client.test@exemple.test",
            seance_id=seance_id,
            place_id=place_id,
            statut=statut,
            qr_code=f"qr-de-test-{billet_id}",
            emis_le=datetime.now(UTC),
        )
        return billet_id


@pytest.fixture
async def base(database_url: str) -> AsyncIterator[Base]:
    """Accès direct à la base ; chaque cas part de tables vides."""
    acces = Base(database_url)
    await acces.vider()
    yield acces


@pytest.fixture
async def seance(base: Base) -> Seance:
    """Séance commune du plan (27 places), semée en base."""
    return await base.semer_seance()


# --- Redis ------------------------------------------------------------------------------------


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


def url_redis(conteneur: DockerContainer) -> str:
    # Sous Windows, « localhost » passe d'abord par IPv6 et Docker Desktop coupe la connexion.
    hote = conteneur.get_container_host_ip().replace("localhost", "127.0.0.1")
    return f"redis://{hote}:{conteneur.get_exposed_port(6379)}/0"


@pytest.fixture(scope="module")
def redis_url(redis: DockerContainer) -> str:
    return url_redis(redis)


def cle_verrou(seance_id: uuid.UUID | str, place_id: uuid.UUID | str) -> str:
    """Clé du verrou d'une place, telle que fixée par le plan : `place:<seance>:<place>`."""
    return f"place:{seance_id}:{place_id}"


class ObservateurRedis:
    """Lecture et écriture directes dans Redis par les tests (clés `place:*`)."""

    def __init__(self, url: str) -> None:
        self.url = url

    def _client(self) -> Redis:
        return Redis.from_url(self.url, decode_responses=True, socket_timeout=10)

    async def vider(self) -> None:
        async with self._client() as client:
            await client.flushdb()

    async def valeur(self, cle: str) -> str | None:
        async with self._client() as client:
            valeur: str | None = await client.get(cle)
            return valeur

    async def pttl(self, cle: str) -> int:
        """PTTL de la clé (-2 : absente, -1 : sans expiration)."""
        async with self._client() as client:
            return int(await client.pttl(cle))

    async def poser(self, cle: str, valeur: str, px: int) -> None:
        async with self._client() as client:
            await client.set(cle, valeur, px=px)

    async def supprimer(self, cle: str) -> None:
        async with self._client() as client:
            await client.delete(cle)

    async def cles(self) -> list[str]:
        async with self._client() as client:
            return sorted([cle async for cle in client.scan_iter(match="place:*")])


@pytest.fixture
async def observateur(redis_url: str) -> ObservateurRedis:
    """Observateur de Redis ; chaque cas part d'un Redis vide."""
    acces = ObservateurRedis(redis_url)
    await acces.vider()
    return acces


# --- Jetons et application --------------------------------------------------------------------


@pytest.fixture
def emetteur() -> EmetteurDeTest:
    return EmetteurDeTest()


def entetes_service(emetteur: EmetteurDeTest) -> dict[str, str]:
    """Jeton du client `services` avec le scope seats:lock (données communes du plan)."""
    return emetteur.entetes(sujet="service-test", client="services", scopes=["seats:lock"])


def parametres_billets(database_url: str, **reglages: Any) -> Parametres:
    reglages.setdefault("instance", "billets-test")
    reglages.setdefault("consul_actif", False)
    return Parametres(database_url=database_url, **reglages)


@dataclass
class Plateforme:
    """Deux instances de billets sur la même base et le même Redis, et leurs clients."""

    apps: tuple[FastAPI, FastAPI]
    instance_1: httpx.AsyncClient
    instance_2: httpx.AsyncClient
    public: httpx.AsyncClient
    reglages: dict[str, Any]

    @property
    def instances(self) -> tuple[httpx.AsyncClient, httpx.AsyncClient]:
        return (self.instance_1, self.instance_2)

    def instance(self, numero: int) -> httpx.AsyncClient:
        """Instance n° `numero` modulo 2 : répartit des appels simultanés sur les deux."""
        return self.instances[numero % 2]

    @property
    def duree_reservation(self) -> int:
        return int(self.reglages.get("duree_verrou_reservation", DUREE_RESERVATION))

    @property
    def duree_confirmation(self) -> int:
        return int(self.reglages.get("duree_verrou_confirmation", DUREE_CONFIRMATION))

    async def verrouiller(
        self,
        seance_id: uuid.UUID,
        place_id: uuid.UUID | str,
        commande_id: uuid.UUID,
        *,
        confirmation: bool | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> httpx.Response:
        corps: dict[str, Any] = {"seance_id": str(seance_id), "commande_id": str(commande_id)}
        if confirmation is not None:
            corps["confirmation"] = confirmation
        appelant = client or self.instance_1
        return await appelant.put(f"{ROUTE_PLACES}/{place_id}/lock", json=corps)

    async def places(self, seance_id: uuid.UUID, **pagination: int) -> httpx.Response:
        parametres: dict[str, Any] = {"seance_id": str(seance_id), **pagination}
        return await self.public.get(ROUTE_PLACES, params=parametres)

    async def disponibilites(self, seance_id: uuid.UUID) -> dict[str, bool]:
        """Disponibilité de chaque place (identifiant -> disponible), en une page de 100."""
        reponse = await self.places(seance_id, size=100)
        assert reponse.status_code == 200, (
            f"GET {ROUTE_PLACES} : {reponse.status_code} au lieu de 200 : {reponse.text}"
        )
        return {element["id"]: element["disponible"] for element in reponse.json()["elements"]}


@pytest.fixture
def plateforme_billets(
    database_url: str,
    redis_url: str,
    emetteur: EmetteurDeTest,
    base: Base,
    observateur: ObservateurRedis,
) -> Callable[..., AbstractAsyncContextManager[Plateforme]]:
    """Fabrique : `async with plateforme_billets(**reglages) as p` (deux instances)."""

    @asynccontextmanager
    async def demarrer(**reglages: Any) -> AsyncIterator[Plateforme]:
        complets = {"redis_url": redis_url, **reglages}
        apps = tuple(
            creer_app(
                parametres_billets(database_url, instance=f"billets-{numero}", **complets),
                verificateur_jetons=emetteur.verificateur(),
            )
            for numero in (1, 2)
        )
        transports = [httpx.ASGITransport(app=app) for app in apps]
        service = entetes_service(emetteur)
        async with (
            apps[0].router.lifespan_context(apps[0]),
            apps[1].router.lifespan_context(apps[1]),
            httpx.AsyncClient(
                transport=transports[0],
                base_url="http://test",
                headers=service,
                timeout=DELAI_APPEL,
            ) as instance_1,
            httpx.AsyncClient(
                transport=transports[1],
                base_url="http://test",
                headers=service,
                timeout=DELAI_APPEL,
            ) as instance_2,
            httpx.AsyncClient(
                transport=transports[0], base_url="http://test", timeout=DELAI_APPEL
            ) as public,
        ):
            yield Plateforme((apps[0], apps[1]), instance_1, instance_2, public, complets)

    return demarrer


@pytest.fixture
async def plateforme(
    plateforme_billets: Callable[..., AbstractAsyncContextManager[Plateforme]],
) -> AsyncIterator[Plateforme]:
    """Deux instances, durées par défaut (600 s et 3600 s)."""
    async with plateforme_billets() as demarree:
        yield demarree


@pytest.fixture
async def plateforme_courte(
    plateforme_billets: Callable[..., AbstractAsyncContextManager[Plateforme]],
) -> AsyncIterator[Plateforme]:
    """Deux instances, durées courtes du plan (réservation 2 s, confirmation 4 s)."""
    async with plateforme_billets(**DUREES_COURTES) as demarree:
        yield demarree


# --- Outils -----------------------------------------------------------------------------------


def exiger_statut(reponse: httpx.Response, attendu: int, etape: str) -> dict[str, Any]:
    """Statut attendu, sinon AssertionError qui nomme l'étape et donne le corps reçu."""
    assert reponse.status_code == attendu, (
        f"{etape} : {reponse.status_code} au lieu de {attendu} : {reponse.text}"
    )
    corps: dict[str, Any] = reponse.json()
    return corps


def exiger_probleme(reponse: httpx.Response, statut: int, code: str, etape: str) -> None:
    corps = exiger_statut(reponse, statut, etape)
    assert reponse.headers["content-type"].startswith("application/problem+json"), etape
    assert corps["code"] == code, f"{etape} : {corps}"


def lire_instant(valeur: str) -> datetime:
    instant = datetime.fromisoformat(valeur)
    assert instant.tzinfo is not None, f"date sans fuseau : {valeur}"
    return instant


def exiger_expiration(corps: dict[str, Any], secondes: float, etape: str) -> None:
    """`expire_le` ≈ maintenant + `secondes` (tolérance de la décision Q16)."""
    attendu = datetime.now(UTC) + timedelta(seconds=secondes)
    ecart = abs(lire_instant(corps["expire_le"]) - attendu)
    assert ecart <= TOLERANCE_EXPIRATION, (
        f"{etape} : expire_le={corps['expire_le']}, attendu ≈ {attendu.isoformat()}"
    )


async def borne[T](etape: str, attente: Awaitable[T], delai: float = DELAI_APPEL) -> T:
    """Attend `attente` au plus `delai` secondes, sinon AssertionError qui nomme l'étape."""
    debut = time.monotonic()
    with anyio.move_on_after(delai):
        return await attente
    raise AssertionError(
        f"{etape} : pas de réponse en {delai:.0f} s ({time.monotonic() - debut:.0f} s mesurées)"
    )


@pytest.fixture(scope="session")
def composants() -> dict[str, Any]:
    contrat: dict[str, Any] = yaml.safe_load(CONTRAT.read_text(encoding="utf-8"))
    return contrat["components"]  # type: ignore[no-any-return]


def erreurs_schema(corps: Any, schema: str, composants: dict[str, Any]) -> list[str]:
    validateur = Draft202012Validator(
        {"$ref": f"#/components/schemas/{schema}", "components": composants},
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    return [f"{list(e.absolute_path)} : {e.message}" for e in validateur.iter_errors(corps)]


@dataclass(frozen=True)
class Outils:
    """Outils et constantes du conftest, passés aux tests par la fixture `outils` (le mode
    importlib de pytest ne permet pas d'importer le conftest)."""

    route_places: str = ROUTE_PLACES
    nombre_places: int = NOMBRE_PLACES
    duree_reservation: int = DUREE_RESERVATION
    duree_confirmation: int = DUREE_CONFIRMATION
    durees_courtes: dict[str, Any] = field(default_factory=lambda: dict(DUREES_COURTES))
    cle_verrou: Callable[[uuid.UUID | str, uuid.UUID | str], str] = cle_verrou
    exiger_statut: Callable[..., dict[str, Any]] = exiger_statut
    exiger_probleme: Callable[..., None] = exiger_probleme
    exiger_expiration: Callable[..., None] = exiger_expiration
    lire_instant: Callable[[str], datetime] = lire_instant
    borne: Callable[..., Any] = borne
    erreurs_schema: Callable[..., list[str]] = erreurs_schema
    url_redis: Callable[[DockerContainer], str] = url_redis
    parametres_billets: Callable[..., Parametres] = parametres_billets
    entetes_service: Callable[[EmetteurDeTest], dict[str, str]] = entetes_service


@pytest.fixture(scope="session")
def outils() -> Outils:
    return Outils()
