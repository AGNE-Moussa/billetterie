"""Outbox, relais et consommateurs idempotents contre un vrai PostgreSQL et un vrai RabbitMQ."""

import logging
import socket
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

import anyio
import pytest
import sqlalchemy as sa
from faststream.rabbit import RabbitBroker, RabbitQueue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from commun.consommateurs import consommateur_idempotent, file_erreur, messagerie
from commun.evenements import Evenement
from commun.outbox import (
    EXCHANGE_TICKETING,
    METADONNEES_MESSAGERIE,
    OUTBOX,
    RelaisOutbox,
    publier_plus_tard,
)

pytestmark = pytest.mark.anyio

IMAGE_RABBITMQ = "rabbitmq:3.13.7-management-alpine"
UTILISATEUR, MOT_DE_PASSE = "essai", "essai"

# Table métier du test : l'effet d'un consommateur, et l'écriture qui accompagne l'événement.
METADONNEES_TEST = sa.MetaData()
COMMANDES = sa.Table("commandes", METADONNEES_TEST, sa.Column("id", sa.Uuid(), primary_key=True))
EFFETS = sa.Table(
    "effets",
    METADONNEES_TEST,
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("evenement_id", sa.Uuid(), nullable=False),
)


def _port_libre() -> int:
    with socket.socket() as prise:
        prise.bind(("127.0.0.1", 0))
        port: int = prise.getsockname()[1]
        return port


class Rabbit:
    """RabbitMQ sur un port hôte fixe : il garde son adresse quand on l'arrête et le relance."""

    def __init__(self) -> None:
        self.port = _port_libre()
        self.conteneur = (
            DockerContainer(IMAGE_RABBITMQ)
            .with_env("RABBITMQ_DEFAULT_USER", UTILISATEUR)
            .with_env("RABBITMQ_DEFAULT_PASS", MOT_DE_PASSE)
            .with_bind_ports(5672, self.port)
            .waiting_for(LogMessageWaitStrategy("Server startup complete"))
        )
        self.url = f"amqp://{UTILISATEUR}:{MOT_DE_PASSE}@127.0.0.1:{self.port}/"

    def arreter(self) -> None:
        self.conteneur.get_wrapped_container().stop()

    def relancer(self, delai: float = 60.0) -> None:
        self.conteneur.get_wrapped_container().start()
        limite = time.monotonic() + delai
        while time.monotonic() < limite:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=1):
                    pass
                time.sleep(3)  # le port s'ouvre un peu avant que le broker accepte AMQP
                return
            except OSError:
                time.sleep(1)
        raise TimeoutError("RabbitMQ n'a pas redémarré à temps")


@pytest.fixture(scope="module")
def rabbit() -> Iterator[Rabbit]:
    instance = Rabbit()
    with instance.conteneur:
        yield instance


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer("postgres:16.10-alpine", driver="asyncpg") as pg:
        yield pg.get_connection_url().replace("localhost", "127.0.0.1")


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    moteur = create_async_engine(database_url)
    async with moteur.begin() as connexion:
        for metadonnees in (METADONNEES_MESSAGERIE, METADONNEES_TEST):
            await connexion.run_sync(metadonnees.drop_all)
            await connexion.run_sync(metadonnees.create_all)
    yield async_sessionmaker(moteur, expire_on_commit=False)
    await moteur.dispose()


async def _jusqua(predicat: Callable[[], Awaitable[bool]], delai: float = 30.0) -> None:
    """Attend qu'une fonction asynchrone sans argument renvoie vrai."""
    limite = time.monotonic() + delai
    while time.monotonic() < limite:
        if await predicat():
            return
        await anyio.sleep(0.2)
    raise AssertionError("Condition jamais remplie")


def _ecouteur(broker: RabbitBroker, recus: list[Evenement]) -> None:
    """File de test qui reçoit tous les événements de l'exchange ticketing."""
    file = RabbitQueue(f"essai-{uuid.uuid4()}", auto_delete=True, routing_key="ticketing.#")

    @broker.subscriber(file, EXCHANGE_TICKETING)
    async def noter(evenement: Evenement) -> None:
        recus.append(evenement)


async def _ecrire_commande(sessions: async_sessionmaker[AsyncSession]) -> Evenement:
    """Écriture métier et événement dans la même transaction."""
    commande = uuid.uuid4()
    evenement = Evenement.creer("ticketing.order.confirmed", {"commande_id": str(commande)})
    async with sessions() as session, session.begin():
        await session.execute(sa.insert(COMMANDES).values(id=commande))
        await publier_plus_tard(session, evenement)
    return evenement


async def _en_attente(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        requete = sa.select(sa.func.count()).where(OUTBOX.c.envoye_le.is_(None))
        return int((await session.execute(requete)).scalar_one())


async def test_une_ecriture_annulee_n_emet_aucun_evenement(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    evenement = Evenement.creer("ticketing.order.confirmed", {})
    with pytest.raises(RuntimeError):
        async with sessions() as session, session.begin():
            await session.execute(sa.insert(COMMANDES).values(id=uuid.uuid4()))
            await publier_plus_tard(session, evenement)
            raise RuntimeError("échec de l'écriture métier")

    assert await _en_attente(sessions) == 0


async def test_broker_arrete_pendant_l_ecriture_l_evenement_part_au_redemarrage(
    rabbit: Rabbit, sessions: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="commun.outbox")
    recus: list[Evenement] = []
    broker = RabbitBroker(rabbit.url, reconnect_interval=1.0)
    _ecouteur(broker, recus)
    relais = RelaisOutbox(sessions, broker)
    async with messagerie(broker):
        rabbit.arreter()
        try:
            # L'écriture métier réussit sans broker : l'événement attend dans l'outbox.
            evenement = await _ecrire_commande(sessions)
            for _ in range(3):
                assert await relais.publier_en_attente() == 0
            assert await _en_attente(sessions) == 1
        finally:
            rabbit.relancer()

        # CA1 : au retour du broker, le relais publie l'événement.
        async def publie() -> bool:
            await relais.publier_en_attente()
            return await _en_attente(sessions) == 0 and bool(recus)

        await _jusqua(publie, delai=60.0)

    assert [recu.id for recu in recus] == [evenement.id]
    assert recus[0].data == evenement.data
    assert recus[0].correlation_id == evenement.correlation_id
    # La panne est signalée une fois à son début, une fois à sa fin, pas à chaque passe.
    messages = [r.getMessage() for r in caplog.records if r.name == "commun.outbox"]
    assert messages.count("Publication impossible, événements gardés dans l'outbox") == 1
    assert messages.count("Publication rétablie, envoi des événements en attente") == 1


async def test_deux_relais_en_parallele_ne_publient_pas_deux_fois(
    rabbit: Rabbit, sessions: async_sessionmaker[AsyncSession]
) -> None:
    recus: list[Evenement] = []
    broker = RabbitBroker(rabbit.url)
    _ecouteur(broker, recus)
    evenements = [await _ecrire_commande(sessions) for _ in range(40)]
    async with messagerie(broker):
        relais = [RelaisOutbox(sessions, broker, taille_lot=5) for _ in range(2)]

        async def vider(un_relais: RelaisOutbox) -> None:
            while await un_relais.publier_en_attente():
                pass

        async with anyio.create_task_group() as groupe:
            for un_relais in relais:
                groupe.start_soon(vider, un_relais)

        async def tout_recu() -> bool:
            return len(recus) >= len(evenements)

        await _jusqua(tout_recu)
        await anyio.sleep(1)  # laisse arriver un éventuel doublon

    assert sorted(str(r.id) for r in recus) == sorted(str(e.id) for e in evenements)


async def _effets(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        return int(
            (await session.execute(sa.select(sa.func.count()).select_from(EFFETS))).scalar_one()
        )


async def test_un_message_livre_deux_fois_ne_produit_qu_un_effet(
    rabbit: Rabbit, sessions: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="commun.consommateurs")
    broker = RabbitBroker(rabbit.url)
    nom = f"billets.order-confirmed-{uuid.uuid4().hex[:8]}"
    appels: list[uuid.UUID] = []

    @consommateur_idempotent(broker, sessions, nom=nom, type_evenement="ticketing.order.confirmed")
    async def emettre_billet(session: AsyncSession, evenement: Evenement) -> None:
        appels.append(evenement.id)
        await session.execute(sa.insert(EFFETS).values(evenement_id=evenement.id))

    evenement = Evenement.creer("ticketing.order.confirmed", {"commande_id": "42"})
    async with messagerie(broker):
        # CA2 : même message (même id) livré deux fois, comme après une republication.
        for _ in range(2):
            await broker.publish(
                evenement.model_dump(mode="json"),
                exchange=EXCHANGE_TICKETING,
                routing_key=evenement.type,
                message_id=str(evenement.id),
            )

        async def deux_livraisons_vues() -> bool:
            return "déjà traité" in caplog.text

        # La seconde livraison est bien arrivée, et elle a été ignorée.
        await _jusqua(deux_livraisons_vues)

    assert appels == [evenement.id]
    assert await _effets(sessions) == 1


async def test_un_message_en_echec_repete_arrive_dans_la_dlq_apres_trois_tentatives(
    rabbit: Rabbit, sessions: async_sessionmaker[AsyncSession]
) -> None:
    broker = RabbitBroker(rabbit.url)
    nom = f"notifications.order-confirmed-{uuid.uuid4().hex[:8]}"
    tentatives: list[uuid.UUID] = []
    en_dlq: list[Evenement] = []

    @consommateur_idempotent(broker, sessions, nom=nom, type_evenement="ticketing.order.confirmed")
    async def envoyer_mail(session: AsyncSession, evenement: Evenement) -> None:
        tentatives.append(evenement.id)
        await session.execute(sa.insert(EFFETS).values(evenement_id=evenement.id))
        raise RuntimeError("serveur SMTP en panne")

    @broker.subscriber(RabbitQueue(file_erreur(nom), declare=False))
    async def lire_dlq(evenement: Evenement) -> None:
        en_dlq.append(evenement)

    evenement = Evenement.creer("ticketing.order.confirmed", {"commande_id": "43"})
    async with messagerie(broker):
        await broker.publish(
            evenement.model_dump(mode="json"),
            exchange=EXCHANGE_TICKETING,
            routing_key=evenement.type,
            message_id=str(evenement.id),
        )

        async def arrive_en_dlq() -> bool:
            return bool(en_dlq)

        await _jusqua(arrive_en_dlq)

    # CA3 : trois tentatives, puis la DLQ ; chaque échec a été annulé (aucun effet gardé).
    assert tentatives == [evenement.id] * 3
    assert [e.id for e in en_dlq] == [evenement.id]
    assert await _effets(sessions) == 0
