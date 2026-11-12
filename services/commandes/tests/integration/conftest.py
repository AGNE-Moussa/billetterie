"""Fixtures d'intégration de commandes (plan docs/test-plans/BIL-008.md, « Doubles et fixtures »).

Montage retenu :

- un conteneur PostgreSQL 16, trois bases (`commandes`, `paiements`, `billets`) migrées par
  `alembic upgrade head` avec le alembic.ini de chaque service ; un vrai Redis 7 pour Billets ;
  jamais de simulacre de base ;
- vrais **Billets** et **Paiements** en ASGI (`httpx.ASGITransport`, sous lifespan) ;
- **Catalogue** : double ASGI minimal qui rend une `Seance` validée contre le schéma du contrat
  catalogue ;
- **Keycloak** : `httpx.MockTransport` qui sert à `JetonService` un jeton `EmetteurDeTest`
  (`client="services"`, scopes `seats:lock payments:write`) ;
- deux applications Commandes (`commandes_1`, `commandes_2`) sur la même base. Leurs clients
  `app.state.catalogue|billets|paiements` (squelette : « remplacés dans les tests ») sont des
  `ClientBilletsHttp`... sur un `commun.http.ClientService` dont le transport est une gateway
  de test : elle aiguille par préfixe (`/api/v1/seats`, `/api/v1/payments`, `/api/v1/shows`),
  enregistre chaque appel et peut simuler une panne (réponse perdue, connexion refusée,
  requête retenue).

Séance `S` du plan : « Fosse » 4500 centimes (A1 à A10), « Balcon » 3000 centimes (C1 à C5),
places insérées dans la base de Billets. Le rang B (Fosse, B1 à B12, repris de BIL-006) est
ajouté pour le seul cas où deux clients prennent chacun 10 places de la même séance.
"""

import asyncio
import json
import os
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
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
from fastapi.responses import JSONResponse
from jsonschema import Draft202012Validator
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from billets.config import Parametres as ParametresBillets
from billets.principal import creer_app as creer_billets
from commandes.config import Parametres as ParametresCommandes
from commandes.infra.clients import (
    CIBLE_BILLETS,
    CIBLE_CATALOGUE,
    CIBLE_PAIEMENTS,
    ClientBilletsHttp,
    ClientCatalogueHttp,
    ClientPaiementsHttp,
)
from commandes.principal import creer_app as creer_commandes
from commun.faux_jetons import EmetteurDeTest
from commun.http import ClientService, Disjoncteur, JetonService
from paiements.config import Parametres as ParametresPaiements
from paiements.principal import creer_app as creer_paiements

RACINE = Path(__file__).resolve().parents[4]
INI = {
    nom: RACINE / "services" / nom / "alembic.ini" for nom in ("commandes", "paiements", "billets")
}
CONTRATS = {
    nom: RACINE / "services" / nom / "openapi.yaml"
    for nom in ("commandes", "paiements", "catalogue")
}
EVENEMENTS = RACINE / "docs" / "evenements"
IMAGE_POSTGRES = "postgres:16.10-alpine"
IMAGE_REDIS = "redis:7.4.6-alpine"
CONNEXION_BORNEE = {"timeout": 30, "command_timeout": 30}
DELAI_APPEL = 60.0

ROUTE_COMMANDES = "/api/v1/orders"
ROUTE_PLACES = "/api/v1/seats"
ROUTE_PAIEMENTS = "/api/v1/payments"
URL_GATEWAY = "http://traefik"
URL_JETON_TEST = "http://keycloak-de-test/realms/billetterie/protocol/openid-connect/token"

CARTE_ACCEPTEE = "4242424242424242"
CARTE_REFUSEE = "4000000000000002"
DUREE_CONFIRMATION_MS = 3_600_000

# Séance S du plan : (catégorie, prix, [(rang, nombre)]) ; rang B : voir la docstring.
CATEGORIES = (
    ("Fosse", 4500, (("A", 10), ("B", 12))),
    ("Balcon", 3000, (("C", 5),)),
)
SCOPES_SERVICE = ("seats:lock", "payments:write")
SCOPES_COMMANDES = ("orders:read", "orders:write")
# Clients du plan (données synthétiques).
CLIENTS: dict[str, dict[str, Any]] = {
    "A": {
        "sujet": "client-a",
        "roles": ["customer"],
        "scopes": list(SCOPES_COMMANDES),
        "email": "client.test@exemple.test",
    },
    "B": {
        "sujet": "client-b",
        "roles": ["customer"],
        "scopes": list(SCOPES_COMMANDES),
        "email": "client.b.test@exemple.test",
    },
    "R1": {
        "sujet": "service-account-revendeur-test",
        "roles": ["partner"],
        "scopes": list(SCOPES_COMMANDES),
        "client": "revendeur-test",
    },
    "R2": {
        "sujet": "service-account-revendeur-test-2",
        "roles": ["partner"],
        "scopes": list(SCOPES_COMMANDES),
        "client": "revendeur-test-2",
    },
}

TABLES = {
    "commandes": ("lignes_commande", "commandes", "outbox", "messages_traites"),
    "paiements": ("paiements", "seances_annulees", "outbox", "messages_traites"),
    "billets": ("billets", "places", "outbox", "messages_traites"),
}


# --- PostgreSQL : un conteneur, trois bases -------------------------------------------------------


def migrer(service: str, database_url: str, cible: str = "head", sens: str = "upgrade") -> None:
    """`alembic upgrade|downgrade <cible>` avec le alembic.ini du service (appel bloquant)."""
    precedente = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        getattr(command, sens)(Config(str(INI[service])), cible)
    finally:
        if precedente is None:
            del os.environ["DATABASE_URL"]
        else:
            os.environ["DATABASE_URL"] = precedente


@dataclass(frozen=True)
class Serveur:
    """Le PostgreSQL du module : fabrique l'URL d'une base et crée de nouvelles bases."""

    hote: str
    port: int
    utilisateur: str
    mot_de_passe: str

    def url(self, base: str) -> str:
        return (
            f"postgresql+asyncpg://{self.utilisateur}:{self.mot_de_passe}"
            f"@{self.hote}:{self.port}/{base}"
        )

    def creer_base(self, nom: str) -> str:
        """Crée la base `nom` (non migrée) et renvoie son URL (appel bloquant)."""

        async def creer() -> None:
            moteur = create_async_engine(
                self.url("commandes"), isolation_level="AUTOCOMMIT", connect_args=CONNEXION_BORNEE
            )
            try:
                async with moteur.connect() as connexion:
                    await connexion.execute(sa.text(f'CREATE DATABASE "{nom}"'))
            finally:
                await moteur.dispose()

        asyncio.run(creer())
        return self.url(nom)


@pytest.fixture(scope="module")
def postgres() -> Iterator[PostgresContainer]:
    mot_de_passe = secrets.token_urlsafe(16)
    with PostgresContainer(
        IMAGE_POSTGRES, username="essai", password=mot_de_passe, dbname="commandes"
    ) as pg:
        pg.mot_de_passe = mot_de_passe  # type: ignore[attr-defined]
        yield pg


@pytest.fixture(scope="module")
def serveur(postgres: PostgresContainer) -> Serveur:
    # Sous Windows, « localhost » passe d'abord par IPv6 et Docker Desktop coupe la connexion.
    hote = postgres.get_container_host_ip().replace("localhost", "127.0.0.1")
    return Serveur(
        hote,
        int(postgres.get_exposed_port(5432)),
        "essai",
        postgres.mot_de_passe,  # type: ignore[attr-defined]
    )


@pytest.fixture(scope="module")
def urls(serveur: Serveur) -> dict[str, str]:
    """Les trois bases migrées avec les vraies migrations de chaque service."""
    resultat = {"commandes": serveur.url("commandes")}
    for nom in ("paiements", "billets"):
        resultat[nom] = serveur.creer_base(nom)
    for nom, url in resultat.items():
        migrer(nom, url)
    return resultat


@pytest.fixture(scope="session")
def migration() -> Callable[..., None]:
    return migrer


class Acces:
    """Lectures et écritures directes dans une base (préparer et vérifier l'état)."""

    def __init__(self, nom: str, url: str) -> None:
        self.nom = nom
        self.url = url

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

    async def compter(self, requete: str, **parametres: Any) -> int:
        lignes = await self._executer(f"SELECT count(*) AS n FROM ({requete}) AS t", parametres)
        return int(lignes[0]["n"])

    async def vider(self) -> None:
        await self._executer(f"TRUNCATE {', '.join(TABLES[self.nom])} CASCADE", {})

    async def contient_texte(self, texte: str) -> list[str]:
        """Tables dont une ligne, rendue en texte, contient `texte` (toutes colonnes)."""
        tables = await self._executer(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'", {}
        )
        trouvees = []
        for ligne in tables:
            table = ligne["table_name"]
            n = await self._executer(
                f'SELECT count(*) AS n FROM "{table}" AS t WHERE t::text LIKE :motif',  # noqa: S608
                {"motif": f"%{texte}%"},
            )
            if int(n[0]["n"]):
                trouvees.append(table)
        return trouvees


@dataclass(frozen=True)
class Bases:
    commandes: Acces
    paiements: Acces
    billets: Acces

    async def vider(self) -> None:
        for acces in (self.commandes, self.paiements, self.billets):
            await acces.vider()

    async def commande(self, commande_id: str | uuid.UUID) -> dict[str, Any]:
        lignes = await self.commandes.lignes(
            "SELECT * FROM commandes WHERE id = :id", id=uuid.UUID(str(commande_id))
        )
        assert len(lignes) == 1, f"commande {commande_id} absente de la base : {lignes}"
        return lignes[0]

    async def commandes_de(self, client: str) -> list[dict[str, Any]]:
        return await self.commandes.lignes(
            "SELECT * FROM commandes WHERE client = :client ORDER BY cree_le", client=client
        )

    async def outbox(self, type_evenement: str | None = None) -> list[dict[str, Any]]:
        requete = "SELECT xmin::text AS xmin, * FROM outbox"
        if type_evenement:
            return await self.commandes.lignes(requete + " WHERE type = :type", type=type_evenement)
        return await self.commandes.lignes(requete)

    async def evenements_de(self, type_evenement: str, commande_id: str) -> list[dict[str, Any]]:
        return [
            ligne
            for ligne in await self.outbox(type_evenement)
            if ligne["data"].get("commande_id") == str(commande_id)
        ]

    async def xmin_commande(self, commande_id: str) -> str:
        lignes = await self.commandes.lignes(
            "SELECT xmin::text AS xmin FROM commandes WHERE id = :id", id=uuid.UUID(commande_id)
        )
        assert lignes, f"commande {commande_id} absente de la base"
        return str(lignes[0]["xmin"])

    async def paiements_de(
        self, commande_id: str | uuid.UUID | None = None
    ) -> list[dict[str, Any]]:
        if commande_id is None:
            return await self.paiements.lignes("SELECT * FROM paiements")
        return await self.paiements.lignes(
            "SELECT * FROM paiements WHERE commande_id = :id", id=uuid.UUID(str(commande_id))
        )

    async def annuler_dans_paiements(self, seance_id: uuid.UUID) -> None:
        await self.paiements.executer(
            "INSERT INTO seances_annulees (seance_id, annulee_le) VALUES (:id, :le)",
            id=seance_id,
            le=datetime.now(UTC),
        )

    async def vendre(self, seance_id: uuid.UUID, place_id: uuid.UUID) -> None:
        """Billet synthétique dans la base de Billets (colonnes de sa migration 0003)."""
        billet_id = uuid.uuid4()
        await self.billets.executer(
            "INSERT INTO billets (id, commande_id, client, seance_id, place_id, statut, qr_code,"
            " emis_le) VALUES (:id, :commande_id, :client, :seance_id, :place_id, 'EMIS',"
            " :qr, :le)",
            id=billet_id,
            commande_id=uuid.uuid4(),
            client="client-autre",
            seance_id=seance_id,
            place_id=place_id,
            qr=f"qr-de-test-{billet_id}",
            le=datetime.now(UTC),
        )


@pytest.fixture
async def bases(urls: dict[str, str]) -> Bases:
    """Accès direct aux trois bases ; chaque cas part de tables vides."""
    acces = Bases(*(Acces(nom, urls[nom]) for nom in ("commandes", "paiements", "billets")))
    await acces.vider()
    return acces


# --- Redis --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def redis_url() -> Iterator[str]:
    conteneur = (
        DockerContainer(IMAGE_REDIS)
        .with_exposed_ports(6379)
        .waiting_for(LogMessageWaitStrategy("Ready to accept connections"))
    )
    with conteneur:
        hote = conteneur.get_container_host_ip().replace("localhost", "127.0.0.1")
        yield f"redis://{hote}:{conteneur.get_exposed_port(6379)}/0"


def cle_verrou(seance_id: uuid.UUID | str, place_id: uuid.UUID | str) -> str:
    return f"place:{seance_id}:{place_id}"


class ObservateurRedis:
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
        async with self._client() as client:
            return int(await client.pttl(cle))

    async def poser(self, cle: str, valeur: str, px: int) -> None:
        async with self._client() as client:
            await client.set(cle, valeur, px=px)


@pytest.fixture
async def redis(redis_url: str) -> ObservateurRedis:
    observateur = ObservateurRedis(redis_url)
    await observateur.vider()
    return observateur


# --- Schémas des contrats et des événements -----------------------------------------------------


def _composants(service: str) -> dict[str, Any]:
    contrat: dict[str, Any] = yaml.safe_load(CONTRATS[service].read_text(encoding="utf-8"))
    return contrat["components"]  # type: ignore[no-any-return]


def erreurs_schema(corps: Any, service: str, schema: str) -> list[str]:
    """Écarts de `corps` au schéma `schema` du contrat de `service`."""
    validateur = Draft202012Validator(
        {"$ref": f"#/components/schemas/{schema}", "components": _composants(service)},
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    return [f"{list(e.absolute_path)} : {e.message}" for e in validateur.iter_errors(corps)]


def erreurs_evenement(ligne_outbox: dict[str, Any]) -> list[str]:
    """Écarts de l'enveloppe reconstituée d'une ligne d'outbox au schéma JSON de son type."""
    schema = json.loads((EVENEMENTS / f"{ligne_outbox['type']}.json").read_text(encoding="utf-8"))
    enveloppe = {
        "id": str(ligne_outbox["id"]),
        "type": ligne_outbox["type"],
        "version": ligne_outbox["version"],
        "occurred_at": ligne_outbox["occurred_at"].isoformat(),
        "correlation_id": ligne_outbox["correlation_id"],
        "data": ligne_outbox["data"],
    }
    validateur = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    return [f"{list(e.absolute_path)} : {e.message}" for e in validateur.iter_errors(enveloppe)]


# --- Séance S : base de Billets et double de Catalogue ------------------------------------------


@dataclass(frozen=True)
class Seance:
    """Séance semée : `places["A1"]` est l'identifiant de la place A1, `prix["A1"]` son prix."""

    id: uuid.UUID
    places: dict[str, uuid.UUID]
    prix: dict[str, int]
    categories: dict[str, uuid.UUID]

    def ids(self, *libelles: str) -> list[str]:
        return [str(self.places[libelle]) for libelle in libelles]


class CatalogueDeTest:
    """Double ASGI de Catalogue : `GET /api/v1/shows/{seance_id}` (lireSeanceParId)."""

    def __init__(self) -> None:
        self.seances: dict[str, dict[str, Any]] = {}
        self.app = FastAPI()

        @self.app.get("/api/v1/shows/{seance_id}")
        async def lire(seance_id: str) -> JSONResponse:
            seance = self.seances.get(seance_id)
            if seance is None:
                return JSONResponse(
                    {
                        "type": "about:blank",
                        "title": "Séance introuvable",
                        "status": 404,
                        "detail": f"Aucune séance avec l'identifiant {seance_id}.",
                        "code": "SHOW_NOT_FOUND",
                    },
                    status_code=404,
                    media_type="application/problem+json",
                )
            return JSONResponse(seance)

    def ajouter(self, seance: Seance, debut: datetime, annulee: bool = False) -> None:
        corps = {
            "id": str(seance.id),
            "evenement_id": str(uuid.uuid4()),
            "lieu_id": str(uuid.uuid4()),
            "debut": debut.isoformat(),
            "annulee": annulee,
            "categories": [
                {
                    "id": str(seance.categories[nom]),
                    "nom": nom,
                    "prix": prix,
                    "rangs": [{"rang": r, "nombre_places": n} for r, n in rangs],
                }
                for nom, prix, rangs in CATEGORIES
            ],
        }
        ecarts = erreurs_schema(corps, "catalogue", "Seance")
        assert ecarts == [], f"double de Catalogue hors contrat : {ecarts}"
        self.seances[str(seance.id)] = corps


async def semer_seance(bases: Bases, catalogue: CatalogueDeTest) -> Seance:
    """Séance S : places dans la base de Billets, séance (début dans 30 j) au Catalogue."""
    seance_id = uuid.uuid4()
    places: dict[str, uuid.UUID] = {}
    prix: dict[str, int] = {}
    categories: dict[str, uuid.UUID] = {}
    a_inserer: list[dict[str, Any]] = []
    for nom, montant, rangs in CATEGORIES:
        categorie_id = uuid.uuid4()
        categories[nom] = categorie_id
        for rang, nombre in rangs:
            for numero in range(1, nombre + 1):
                place_id = uuid.uuid4()
                places[f"{rang}{numero}"] = place_id
                prix[f"{rang}{numero}"] = montant
                a_inserer.append(
                    {
                        "id": place_id,
                        "seance_id": seance_id,
                        "rang": rang,
                        "numero": numero,
                        "categorie_id": categorie_id,
                    }
                )
    moteur = create_async_engine(
        bases.billets.url, poolclass=NullPool, connect_args=CONNEXION_BORNEE
    )
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
    seance = Seance(seance_id, places, prix, categories)
    catalogue.ajouter(seance, datetime.now(UTC) + timedelta(days=30))
    return seance


# --- Gateway de test ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Appel:
    """Un appel sortant de Commandes, vu par la gateway de test."""

    cible: str
    methode: str
    chemin: str
    entetes: dict[str, str]
    corps: Any


Intercepteur = Callable[[httpx.Request, httpx.AsyncBaseTransport], Awaitable[httpx.Response]]
PREFIXES = {
    ROUTE_PLACES: CIBLE_BILLETS,
    ROUTE_PAIEMENTS: CIBLE_PAIEMENTS,
    "/api/v1/shows": CIBLE_CATALOGUE,
}


class Gateway(httpx.AsyncBaseTransport):
    """Aiguille par préfixe vers l'ASGI de chaque cible et enregistre chaque appel."""

    def __init__(self, cibles: dict[str, httpx.AsyncBaseTransport]) -> None:
        self.cibles = cibles
        self.appels: list[Appel] = []
        self.intercepteurs: dict[str, Intercepteur] = {}

    def appels_vers(self, cible: str) -> list[Appel]:
        return [appel for appel in self.appels if appel.cible == cible]

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        cible = next(
            (nom for prefixe, nom in PREFIXES.items() if request.url.path.startswith(prefixe)), None
        )
        if cible is None:
            return httpx.Response(404, json={"detail": f"aucune route pour {request.url.path}"})
        contenu = await request.aread()
        self.appels.append(
            Appel(
                cible,
                request.method,
                request.url.path,
                dict(request.headers),
                json.loads(contenu) if contenu else None,
            )
        )
        transport = self.cibles[cible]
        intercepteur = self.intercepteurs.get(cible)
        if intercepteur is not None:
            return await intercepteur(request, transport)
        return await transport.handle_async_request(request)


async def _sans_attente(_secondes: float) -> None:
    """Backoff de ClientService sans attente réelle (les tentatives restent comptées)."""


# --- Plateforme ----------------------------------------------------------------------------------


@dataclass
class Plateforme:
    emetteur: EmetteurDeTest
    gateway: Gateway
    catalogue: CatalogueDeTest
    bases: Bases
    redis: ObservateurRedis
    seance: Seance
    commandes_1: httpx.AsyncClient
    commandes_2: httpx.AsyncClient
    billets: httpx.AsyncClient
    paiements: httpx.AsyncClient
    jetons_emis: list[str] = field(default_factory=list)

    # Appels par l'API de Commandes -----------------------------------------------------------

    def instance(self, numero: int) -> httpx.AsyncClient:
        """Instance n° `numero` modulo 2 : répartit des appels simultanés sur les deux."""
        return (self.commandes_1, self.commandes_2)[numero % 2]

    def entetes(self, qui: str | dict[str, Any], **supplementaires: str) -> dict[str, str]:
        profil = CLIENTS[qui] if isinstance(qui, str) else qui
        jeton = self.emetteur.jeton(**profil)
        self.jetons_emis.append(jeton)
        return {"Authorization": f"Bearer {jeton}", **supplementaires}

    async def commander(
        self,
        qui: str | dict[str, Any],
        libelles: list[str] | tuple[str, ...],
        *,
        seance: Seance | None = None,
        carte: str = CARTE_ACCEPTEE,
        cle: str | None = None,
        correlation: str | None = None,
        instance: httpx.AsyncClient | None = None,
    ) -> httpx.Response:
        seance = seance or self.seance
        entetes = self.entetes(qui)
        if cle is not None:
            entetes["Idempotency-Key"] = cle
        if correlation is not None:
            entetes["X-Correlation-Id"] = correlation
        corps = {
            "seance_id": str(seance.id),
            "place_ids": seance.ids(*libelles),
            "carte_test": carte,
        }
        client = instance or self.commandes_1
        return await borne(
            f"POST {ROUTE_COMMANDES}", client.post(ROUTE_COMMANDES, json=corps, headers=entetes)
        )

    async def payer(
        self,
        qui: str | dict[str, Any],
        commande_id: str,
        *,
        carte: str = CARTE_ACCEPTEE,
        instance: httpx.AsyncClient | None = None,
    ) -> httpx.Response:
        client = instance or self.commandes_1
        return await borne(
            f"POST {ROUTE_COMMANDES}/{{id}}/payment",
            client.post(
                f"{ROUTE_COMMANDES}/{commande_id}/payment",
                json={"carte_test": carte},
                headers=self.entetes(qui),
            ),
        )

    async def lister(self, qui: str | dict[str, Any], **parametres: Any) -> httpx.Response:
        return await borne(
            f"GET {ROUTE_COMMANDES}",
            self.commandes_1.get(ROUTE_COMMANDES, params=parametres, headers=self.entetes(qui)),
        )

    async def lire(self, qui: str | dict[str, Any], commande_id: str) -> httpx.Response:
        return await borne(
            f"GET {ROUTE_COMMANDES}/{{id}}",
            self.commandes_1.get(f"{ROUTE_COMMANDES}/{commande_id}", headers=self.entetes(qui)),
        )

    async def verrouiller_pour_autrui(self, libelle: str) -> uuid.UUID:
        """Verrou de réservation posé par `verrouillerPlace` pour une commande aléatoire."""
        commande_id = uuid.uuid4()
        reponse = await self.billets.put(
            f"{ROUTE_PLACES}/{self.seance.places[libelle]}/lock",
            json={"seance_id": str(self.seance.id), "commande_id": str(commande_id)},
        )
        assert reponse.status_code == 200, f"verrouillerPlace préalable : {reponse.text}"
        return commande_id

    def cle_redis(self, libelle: str, seance: Seance | None = None) -> str:
        seance = seance or self.seance
        return cle_verrou(seance.id, seance.places[libelle])

    async def nouvelle_seance(self) -> Seance:
        return await semer_seance(self.bases, self.catalogue)

    # Pannes simulées (enveloppes de la gateway) ---------------------------------------------

    def paiements_injoignable(self) -> None:
        """Toute requête vers Paiements : ConnectError, sans l'atteindre."""

        async def panne(
            requete: httpx.Request, _transport: httpx.AsyncBaseTransport
        ) -> httpx.Response:
            raise httpx.ConnectError("Paiements injoignable (test)", request=requete)

        self.gateway.intercepteurs[CIBLE_PAIEMENTS] = panne

    def perdre_reponses_paiements(self, nombre: int | None = None) -> list[int]:
        """Laisse passer la requête vers Paiements puis lève ReadTimeout (réponse perdue),
        pour les `nombre` premières requêtes (toutes si None). Renvoie les statuts perdus."""
        perdues: list[int] = []

        async def perdre(
            requete: httpx.Request, transport: httpx.AsyncBaseTransport
        ) -> httpx.Response:
            reponse = await transport.handle_async_request(requete)
            await reponse.aread()
            if nombre is None or len(perdues) < nombre:
                perdues.append(reponse.status_code)
                raise httpx.ReadTimeout("réponse de Paiements perdue (test)", request=requete)
            return reponse

        self.gateway.intercepteurs[CIBLE_PAIEMENTS] = perdre
        return perdues

    def retenir_paiements(self, liberation: asyncio.Event, arrivee: asyncio.Event) -> None:
        """Requête vers Paiements retenue jusqu'à `liberation` ; `arrivee` signale son arrivée."""

        async def retenir(
            requete: httpx.Request, transport: httpx.AsyncBaseTransport
        ) -> httpx.Response:
            arrivee.set()
            await liberation.wait()
            return await transport.handle_async_request(requete)

        self.gateway.intercepteurs[CIBLE_PAIEMENTS] = retenir

    def perdre_place_au_reverrouillage(self, libelle: str) -> None:
        """Juste avant le reverrouillage (`confirmation: true`) de la place, une autre commande
        prend son verrou dans Redis : la place est perdue entre réservation et paiement."""
        place_id = str(self.seance.places[libelle])

        async def voler(
            requete: httpx.Request, transport: httpx.AsyncBaseTransport
        ) -> httpx.Response:
            corps = json.loads(requete.content or b"{}")
            if place_id in requete.url.path and corps.get("confirmation") is True:
                await self.redis.poser(self.cle_redis(libelle), str(uuid.uuid4()), px=600_000)
            return await transport.handle_async_request(requete)

        self.gateway.intercepteurs[CIBLE_BILLETS] = voler

    def retablir(self) -> None:
        self.gateway.intercepteurs.clear()


def keycloak_de_test(emetteur: EmetteurDeTest, jetons: list[str]) -> httpx.MockTransport:
    """Faux point de jeton Keycloak : jeton du client `services` (Client Credentials)."""

    def repondre(_requete: httpx.Request) -> httpx.Response:
        jeton = emetteur.jeton(
            sujet="service-account-services", client="services", scopes=list(SCOPES_SERVICE)
        )
        jetons.append(jeton)
        return httpx.Response(
            200, json={"access_token": jeton, "expires_in": 300, "token_type": "Bearer"}
        )

    return httpx.MockTransport(repondre)


def _client_asgi(app: FastAPI, **options: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        timeout=DELAI_APPEL,
        **options,
    )


@pytest.fixture
def plateforme_commandes(
    urls: dict[str, str], redis_url: str, bases: Bases, redis: ObservateurRedis
) -> Callable[..., AbstractAsyncContextManager[Plateforme]]:
    """Fabrique : `async with plateforme_commandes(billets={...}, commandes={...}) as p`."""

    @asynccontextmanager
    async def demarrer(
        billets: dict[str, Any] | None = None, commandes: dict[str, Any] | None = None
    ) -> AsyncIterator[Plateforme]:
        emetteur = EmetteurDeTest()
        secret = secrets.token_urlsafe(16)
        app_billets = creer_billets(
            ParametresBillets(
                database_url=urls["billets"],
                redis_url=redis_url,
                instance="billets-test",
                consul_actif=False,
                **(billets or {}),
            ),
            verificateur_jetons=emetteur.verificateur(),
        )
        app_paiements = creer_paiements(
            ParametresPaiements(
                database_url=urls["paiements"], instance="paiements-test", consul_actif=False
            ),
            verificateur_jetons=emetteur.verificateur(),
        )
        catalogue = CatalogueDeTest()
        gateway = Gateway(
            {
                CIBLE_BILLETS: httpx.ASGITransport(app=app_billets),
                CIBLE_PAIEMENTS: httpx.ASGITransport(app=app_paiements),
                CIBLE_CATALOGUE: httpx.ASGITransport(app=catalogue.app),
            }
        )
        apps_commandes = [
            creer_commandes(
                ParametresCommandes(
                    database_url=urls["commandes"],
                    instance=f"commandes-{numero}",
                    consul_actif=False,
                    url_gateway=URL_GATEWAY,
                    url_jeton=URL_JETON_TEST,
                    services_client_secret=secret,
                    **(commandes or {}),
                ),
                verificateur_jetons=emetteur.verificateur(),
            )
            for numero in (1, 2)
        ]
        jetons_service: list[str] = []
        service = emetteur.entetes(
            sujet="service-account-services", client="services", scopes=list(SCOPES_SERVICE)
        )
        async with AsyncExitStack() as pile:
            for app in (app_billets, app_paiements, *apps_commandes):
                await pile.enter_async_context(app.router.lifespan_context(app))
            for app in apps_commandes:
                jeton = JetonService(
                    URL_JETON_TEST,
                    "services",
                    secret,
                    transport=keycloak_de_test(emetteur, jetons_service),
                )
                pile.push_async_callback(jeton.aclose)

                def client_service(cible: str, jeton: JetonService = jeton) -> ClientService:
                    client = ClientService(
                        cible,
                        URL_GATEWAY,
                        jeton=jeton,
                        timeout=DELAI_APPEL,
                        transport=gateway,
                        attente=_sans_attente,
                        disjoncteur_cible=Disjoncteur(cible),
                    )
                    pile.push_async_callback(client.aclose)
                    return client

                app.state.catalogue = ClientCatalogueHttp(client_service(CIBLE_CATALOGUE))
                app.state.billets = ClientBilletsHttp(client_service(CIBLE_BILLETS))
                app.state.paiements = ClientPaiementsHttp(client_service(CIBLE_PAIEMENTS))
            commandes_1 = await pile.enter_async_context(_client_asgi(apps_commandes[0]))
            commandes_2 = await pile.enter_async_context(_client_asgi(apps_commandes[1]))
            client_billets = await pile.enter_async_context(
                _client_asgi(app_billets, headers=service)
            )
            client_paiements = await pile.enter_async_context(
                _client_asgi(app_paiements, headers=service)
            )
            seance = await semer_seance(bases, catalogue)
            plateforme = Plateforme(
                emetteur,
                gateway,
                catalogue,
                bases,
                redis,
                seance,
                commandes_1,
                commandes_2,
                client_billets,
                client_paiements,
                # Jetons des clients et jetons de service émis : aucun ne doit être journalisé.
                jetons_emis=jetons_service,
            )
            yield plateforme

    return demarrer


@pytest.fixture
async def plateforme(
    plateforme_commandes: Callable[..., AbstractAsyncContextManager[Plateforme]],
) -> AsyncIterator[Plateforme]:
    """Durées de verrou par défaut (réservation 600 s, confirmation 3600 s)."""
    async with plateforme_commandes() as demarree:
        yield demarree


# --- Outils -------------------------------------------------------------------------------------


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
    """Attend `attente` au plus `delai` secondes, sinon AssertionError qui nomme l'étape."""
    debut = time.monotonic()
    with anyio.move_on_after(delai):
        return await attente
    raise AssertionError(
        f"{etape} : pas de réponse en {delai:.0f} s ({time.monotonic() - debut:.0f} s mesurées)"
    )


async def barriere[T](nombre: int, appel: Callable[[int], Awaitable[T]]) -> list[T]:
    """Crée `nombre` tâches, attend qu'elles soient toutes prêtes, puis les libère ensemble."""
    prets = 0
    tous_prets = asyncio.Event()
    depart = asyncio.Event()

    async def tache(numero: int) -> T:
        nonlocal prets
        prets += 1
        if prets == nombre:
            tous_prets.set()
        await depart.wait()
        return await appel(numero)

    taches = [asyncio.create_task(tache(numero)) for numero in range(nombre)]
    await tous_prets.wait()
    depart.set()
    return list(await borne(f"{nombre} appels simultanés", asyncio.gather(*taches)))


def lire_instant(valeur: str) -> datetime:
    instant = datetime.fromisoformat(valeur)
    assert instant.tzinfo is not None, f"date sans fuseau : {valeur}"
    return instant


@dataclass(frozen=True)
class Outils:
    """Constantes et outils du conftest (le mode importlib ne permet pas de l'importer)."""

    route_commandes: str = ROUTE_COMMANDES
    route_paiements: str = ROUTE_PAIEMENTS
    carte_acceptee: str = CARTE_ACCEPTEE
    carte_refusee: str = CARTE_REFUSEE
    duree_confirmation_ms: int = DUREE_CONFIRMATION_MS
    clients: dict[str, dict[str, Any]] = field(default_factory=lambda: dict(CLIENTS))
    exiger_statut: Callable[..., dict[str, Any]] = exiger_statut
    exiger_probleme: Callable[..., dict[str, Any]] = exiger_probleme
    borne: Callable[..., Any] = borne
    barriere: Callable[..., Any] = barriere
    lire_instant: Callable[[str], datetime] = lire_instant
    erreurs_schema: Callable[..., list[str]] = erreurs_schema
    erreurs_evenement: Callable[[dict[str, Any]], list[str]] = erreurs_evenement
    cle_verrou: Callable[..., str] = cle_verrou


@pytest.fixture(scope="session")
def outils() -> Outils:
    return Outils()
