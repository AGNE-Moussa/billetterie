"""Fixtures d'intégration de notifications (plan docs/test-plans/BIL-009.md).

Vraie base PostgreSQL 16 par module, migrée par `alembic upgrade head` avec
`services/notifications/alembic.ini` ; vrai Mailpit (`axllent/mailpit:v1.27.10`, même image que
compose.yaml : SMTP 1025, API 8025), vidé avant chaque test ; vrai RabbitMQ pour les cas de
livraison. Jamais de simulacre de la base ni du SMTP.

Données synthétiques du plan : commande `C1` (`client.test@exemple.test`), commande revendeur
`R` (`email` null), séance `S` ; aucune adresse réelle (domaine `exemple.test`).
"""

import json
import os
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aio_pika
import anyio
import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from commun.evenements import Evenement
from commun.faux_jetons import EmetteurDeTest
from notifications.config import Parametres
from notifications.principal import creer_app

RACINE = Path(__file__).resolve().parents[4]
ALEMBIC_INI = RACINE / "services" / "notifications" / "alembic.ini"
IMAGE_POSTGRES = "postgres:16.10-alpine"
IMAGE_MAILPIT = "axllent/mailpit:v1.27.10"  # même image que le service mailpit de compose.yaml
IMAGE_RABBITMQ = "rabbitmq:3.13.7-management-alpine"

TABLES_DU_TICKET = ("envois", "destinataires_commande", "outbox", "messages_traites")
CONNEXION_BORNEE = {"timeout": 30, "command_timeout": 30}

EVENEMENT_COMMANDE_CONFIRMEE = "ticketing.order.confirmed"
EVENEMENT_BILLET_EMIS = "ticketing.ticket.issued"
CONSOMMATEUR_COMMANDE_CONFIRMEE = "notifications.order-confirmed"
CONSOMMATEUR_BILLET_EMIS = "notifications.ticket-issued"
CORRELATION = "correlation-bil-009-1"
EMAIL_C1 = "client.test@exemple.test"
EXPEDITEUR = "billetterie@exemple.test"
# Attente d'un effet asynchrone (trois livraisons comprises pour la DLQ).
DELAI_TRAITEMENT = 20.0
# Laisse arriver un éventuel doublon après le premier effet.
ATTENTE_DOUBLON = 2.0


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
    return migrer


@pytest.fixture(scope="module")
def postgres() -> Iterator[PostgresContainer]:
    mot_de_passe = secrets.token_urlsafe(16)
    with PostgresContainer(
        IMAGE_POSTGRES, username="notifications", password=mot_de_passe, dbname="notifications"
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
    return f"postgresql+asyncpg://notifications:{mot_de_passe}@{hote}:{port}/notifications"


@pytest.fixture(scope="module")
def database_url(url_base: str) -> str:
    migrer(url_base)
    return url_base


# --- Accès direct à la base -------------------------------------------------------------------


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

    async def lignes(self, requete: str, **parametres: Any) -> list[Any]:
        return await self._executer(requete, parametres)  # type: ignore[no-any-return]

    async def executer(self, requete: str, **parametres: Any) -> None:
        await self._executer(requete, parametres)

    async def vider(self) -> None:
        presentes = await self.tables()
        a_vider = [table for table in TABLES_DU_TICKET if table in presentes]
        if a_vider:
            await self._executer(f"TRUNCATE {', '.join(a_vider)} CASCADE")

    async def inserer_destinataire(
        self, commande_id: uuid.UUID, email: str | None, seance_id: uuid.UUID
    ) -> None:
        """Destinataire déjà enregistré (colonnes de docs/modele-donnees.md, migration 0003)."""
        await self.executer(
            "INSERT INTO destinataires_commande (commande_id, email, seance_id)"
            " VALUES (:commande_id, :email, :seance_id)",
            commande_id=commande_id,
            email=email,
            seance_id=seance_id,
        )

    async def destinataires(self) -> list[Any]:
        return await self.lignes("SELECT * FROM destinataires_commande")

    async def envois(self) -> list[Any]:
        return await self.lignes("SELECT * FROM envois ORDER BY envoye_le")

    async def traites(self, consommateur: str, message_id: uuid.UUID | None = None) -> int:
        requete = "SELECT count(*) AS n FROM messages_traites WHERE consommateur = :nom"
        parametres: dict[str, Any] = {"nom": consommateur}
        if message_id is not None:
            requete += " AND message_id = :message"
            parametres["message"] = message_id
        lignes = await self.lignes(requete, **parametres)
        return int(lignes[0]["n"])


@pytest.fixture
async def base(database_url: str) -> AsyncIterator[Base]:
    acces = Base(database_url)
    await acces.vider()
    yield acces


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessions du service sur la base du module (une transaction par traitement)."""
    moteur = create_async_engine(database_url, connect_args=CONNEXION_BORNEE)
    try:
        yield async_sessionmaker(moteur, expire_on_commit=False)
    finally:
        await moteur.dispose()


# --- Mailpit ----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mailpit() -> Iterator[DockerContainer]:
    conteneur = DockerContainer(IMAGE_MAILPIT).with_exposed_ports(1025, 8025)
    with conteneur:
        hote = conteneur.get_container_host_ip().replace("localhost", "127.0.0.1")
        api = f"http://{hote}:{conteneur.get_exposed_port(8025)}"
        limite = time.monotonic() + 60
        while True:
            try:
                if httpx.get(f"{api}/api/v1/messages", timeout=2.0).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > limite:
                raise TimeoutError("Mailpit n'a pas démarré à temps")
            time.sleep(0.5)
        yield conteneur


@dataclass
class BoiteMailpit:
    """API de Mailpit (`/api/v1/...`) et adresse SMTP vue depuis l'hôte."""

    conteneur: DockerContainer
    api: str
    smtp_hote: str
    smtp_port: int

    async def messages(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            reponse = await client.get(f"{self.api}/api/v1/messages")
            reponse.raise_for_status()
            return list(reponse.json().get("messages") or [])

    async def message(self, identifiant: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            reponse = await client.get(f"{self.api}/api/v1/message/{identifiant}")
            reponse.raise_for_status()
            corps: dict[str, Any] = reponse.json()
            return corps

    async def partie(self, identifiant: str, partie: str) -> bytes:
        async with httpx.AsyncClient(timeout=10.0) as client:
            reponse = await client.get(f"{self.api}/api/v1/message/{identifiant}/part/{partie}")
            reponse.raise_for_status()
            return reponse.content

    async def vider(self) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            (await client.delete(f"{self.api}/api/v1/messages")).raise_for_status()

    async def attendre(self, nombre: int, delai: float = DELAI_TRAITEMENT) -> list[dict[str, Any]]:
        """Messages reçus dès qu'il y en a au moins `nombre`, ou ceux présents à l'échéance."""
        limite = time.monotonic() + delai
        while True:
            recus = await self.messages()
            if len(recus) >= nombre or time.monotonic() > limite:
                return recus
            await anyio.sleep(0.5)

    async def images_png(self, identifiant: str) -> list[bytes]:
        """Contenu des pièces jointes `image/png` du message (jointes ou en ligne)."""
        detail = await self.message(identifiant)
        parties = list(detail.get("Attachments") or []) + list(detail.get("Inline") or [])
        return [
            await self.partie(identifiant, partie["PartID"])
            for partie in parties
            if partie.get("ContentType") == "image/png"
        ]


@pytest.fixture
async def boite(mailpit: DockerContainer) -> BoiteMailpit:
    """Mailpit du module, vidé avant chaque test."""
    hote = mailpit.get_container_host_ip().replace("localhost", "127.0.0.1")
    acces = BoiteMailpit(
        mailpit,
        f"http://{hote}:{mailpit.get_exposed_port(8025)}",
        hote,
        int(mailpit.get_exposed_port(1025)),
    )
    await acces.vider()
    return acces


# --- RabbitMQ et application ------------------------------------------------------------------


@pytest.fixture(scope="module")
def rabbitmq_url() -> Iterator[str]:
    utilisateur, mot_de_passe = "essai", secrets.token_urlsafe(16)
    conteneur = (
        DockerContainer(IMAGE_RABBITMQ)
        .with_env("RABBITMQ_DEFAULT_USER", utilisateur)
        .with_env("RABBITMQ_DEFAULT_PASS", mot_de_passe)
        .with_exposed_ports(5672)
        .waiting_for(LogMessageWaitStrategy("Server startup complete"))
    )
    with conteneur:
        hote = conteneur.get_container_host_ip().replace("localhost", "127.0.0.1")
        yield f"amqp://{utilisateur}:{mot_de_passe}@{hote}:{conteneur.get_exposed_port(5672)}/"


@pytest.fixture
def service_notifications(
    database_url: str, rabbitmq_url: str, boite: BoiteMailpit, base: Base
) -> Callable[..., AbstractAsyncContextManager[None]]:
    """Fabrique : `async with service_notifications(**reglages)` démarre le service (lifespan)
    avec ses consommateurs RabbitMQ et le SMTP de Mailpit."""

    @asynccontextmanager
    async def demarrer(**reglages: Any) -> AsyncIterator[None]:
        reglages.setdefault("smtp_hote", boite.smtp_hote)
        reglages.setdefault("smtp_port", boite.smtp_port)
        config = Parametres(
            database_url=database_url,
            rabbitmq_url=rabbitmq_url,
            consul_actif=False,
            instance="notifications-test",
            **reglages,
        )
        app = creer_app(config, verificateur_jetons=EmetteurDeTest().verificateur())
        async with app.router.lifespan_context(app):
            yield

    return demarrer


# --- Données et outils ------------------------------------------------------------------------


def donnees_commande(
    commande_id: uuid.UUID,
    seance_id: uuid.UUID,
    place_ids: list[uuid.UUID],
    *,
    client: str = "client-test",
    email: str | None = EMAIL_C1,
) -> dict[str, Any]:
    """`data` de ticketing.order.confirmed (docs/evenements), lignes à 4500 centimes."""
    return {
        "commande_id": str(commande_id),
        "client": client,
        "email": email,
        "seance_id": str(seance_id),
        "lignes": [{"place_id": str(place), "montant": 4500} for place in place_ids],
        "montant_total": 4500 * len(place_ids),
    }


def donnees_billet(
    commande_id: uuid.UUID, seance_id: uuid.UUID, place_id: uuid.UUID
) -> dict[str, Any]:
    """`data` de ticketing.ticket.issued v1 ; QR synthétique (`<billet_id>.<signature>`)."""
    billet_id = uuid.uuid4()
    return {
        "billet_id": str(billet_id),
        "commande_id": str(commande_id),
        "seance_id": str(seance_id),
        "place_id": str(place_id),
        "qr_code": f"{billet_id}.{secrets.token_urlsafe(32)}",
        "emis_le": "2026-11-12T10:00:00+00:00",
    }


def evenement(
    type_evenement: str, data: dict[str, Any], identifiant: uuid.UUID | None = None
) -> Evenement:
    return Evenement(
        id=identifiant or uuid.uuid4(),
        type=type_evenement,
        version=1,
        correlation_id=CORRELATION,
        data=data,
    )


@dataclass(frozen=True)
class CommandeDeTest:
    """Commande synthétique du plan et ses places."""

    commande_id: uuid.UUID
    seance_id: uuid.UUID
    places: dict[str, uuid.UUID]
    email: str | None
    client: str

    def order_confirmed(self, identifiant: uuid.UUID | None = None) -> Evenement:
        return evenement(
            EVENEMENT_COMMANDE_CONFIRMEE,
            donnees_commande(
                self.commande_id,
                self.seance_id,
                list(self.places.values()),
                client=self.client,
                email=self.email,
            ),
            identifiant,
        )

    def ticket_issued(self, libelle: str) -> Evenement:
        return evenement(
            EVENEMENT_BILLET_EMIS,
            donnees_billet(self.commande_id, self.seance_id, self.places[libelle]),
        )


def commande_c1() -> CommandeDeTest:
    return CommandeDeTest(
        uuid.uuid4(),
        uuid.uuid4(),
        {"A1": uuid.uuid4(), "A2": uuid.uuid4()},
        EMAIL_C1,
        "client-test",
    )


def commande_revendeur() -> CommandeDeTest:
    return CommandeDeTest(uuid.uuid4(), uuid.uuid4(), {"A3": uuid.uuid4()}, None, "revendeur-test")


async def publier(rabbitmq_url: str, *evenements: Evenement) -> None:
    """Publie sur l'exchange `ticketing` (topic, durable), comme le relais de l'outbox."""
    connexion = await aio_pika.connect_robust(rabbitmq_url)
    async with connexion:
        canal = await connexion.channel()
        exchange = await canal.declare_exchange(
            "ticketing", aio_pika.ExchangeType.TOPIC, durable=True
        )
        for un_evenement in evenements:
            await exchange.publish(
                aio_pika.Message(
                    body=json.dumps(un_evenement.model_dump(mode="json")).encode(),
                    content_type="application/json",
                    message_id=str(un_evenement.id),
                    correlation_id=un_evenement.correlation_id,
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                routing_key=un_evenement.type,
            )


async def lire_file_erreur(rabbitmq_url: str, consommateur: str) -> list[str]:
    """Identifiants des messages présents dans `<consommateur>.dlq` (consommés)."""
    connexion = await aio_pika.connect_robust(rabbitmq_url)
    identifiants: list[str] = []
    async with connexion:
        canal = await connexion.channel()
        file = await canal.declare_queue(f"{consommateur}.dlq", passive=True)
        while (message := await file.get(no_ack=True, fail=False)) is not None:
            identifiants.append(str(json.loads(message.body)["id"]))
    return identifiants


async def jusqua(predicat: Callable[[], Awaitable[bool]], delai: float = DELAI_TRAITEMENT) -> bool:
    limite = time.monotonic() + delai
    while time.monotonic() < limite:
        if await predicat():
            return True
        await anyio.sleep(0.5)
    return False


async def traiter(
    sessions: async_sessionmaker[AsyncSession],
    traitement: Callable[[AsyncSession, Evenement], Awaitable[None]],
    un_evenement: Evenement,
) -> BaseException | None:
    """Un traitement du service dans sa propre session et sa transaction ; rend l'exception
    levée (ou None), pour que le test vérifie d'abord l'état observable."""
    try:
        async with sessions() as session, session.begin():
            await traitement(session, un_evenement)
    except Exception as erreur:  # noqa: BLE001 : classée par le test
        return erreur
    return None


@dataclass(frozen=True)
class Outils:
    """Outils et constantes du conftest (le mode importlib ne permet pas de l'importer)."""

    correlation: str = CORRELATION
    email_c1: str = EMAIL_C1
    expediteur: str = EXPEDITEUR
    evenement_billet_emis: str = EVENEMENT_BILLET_EMIS
    consommateur_commande: str = CONSOMMATEUR_COMMANDE_CONFIRMEE
    consommateur_billet: str = CONSOMMATEUR_BILLET_EMIS
    attente_doublon: float = ATTENTE_DOUBLON
    delai_traitement: float = DELAI_TRAITEMENT
    tables_du_ticket: tuple[str, ...] = field(default_factory=lambda: TABLES_DU_TICKET)
    commande_c1: Callable[[], CommandeDeTest] = commande_c1
    commande_revendeur: Callable[[], CommandeDeTest] = commande_revendeur
    publier: Callable[..., Awaitable[None]] = publier
    lire_file_erreur: Callable[..., Awaitable[list[str]]] = lire_file_erreur
    jusqua: Callable[..., Awaitable[bool]] = jusqua
    traiter: Callable[..., Awaitable[BaseException | None]] = traiter


@pytest.fixture(scope="session")
def outils() -> Outils:
    return Outils()
