"""Consommateurs idempotents, avec file d'erreur (DLQ) après trois tentatives.

    @consommateur_idempotent(broker, sessions, nom="billets.order-confirmed",
                             type_evenement="ticketing.order.confirmed")
    async def emettre_billet(session: AsyncSession, evenement: Evenement) -> None:
        ...

    async with messagerie(broker):   # lifespan : déclare les DLQ puis démarre les consommateurs
        ...

- Idempotence : l'identifiant du message est inscrit dans `messages_traites` dans la même
  transaction que l'effet du traitement. Un doublon trouve l'identifiant et n'a aucun effet.
- Tentatives : un traitement en erreur est annulé (rollback) et le message remis en file. La file
  est une quorum queue : RabbitMQ compte les livraisons et, au-delà de la limite, envoie le
  message dans `<nom>.dlq` par l'exchange `ticketing.dlx`. Le compte survit à un plantage.
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from faststream import AckPolicy
from faststream.rabbit import ExchangeType, QueueType, RabbitBroker, RabbitExchange, RabbitQueue
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commun.correlation import correlation
from commun.evenements import Evenement
from commun.outbox import EXCHANGE_TICKETING, MESSAGES_TRAITES

journal = logging.getLogger(__name__)

TENTATIVES = 3
EXCHANGE_ERREURS = RabbitExchange("ticketing.dlx", type=ExchangeType.DIRECT, durable=True)

Traitement = Callable[[AsyncSession, Evenement], Awaitable[None]]
# Action lancée après le commit de la transaction (ou si le message était déjà traité), hors de
# toute transaction : par exemple supprimer des verrous Redis (BIL-009).
ApresCommit = Callable[[Evenement], Awaitable[None]]

# Files d'erreur à déclarer avant le démarrage des consommateurs, par broker.
_files_erreur: dict[int, list[RabbitQueue]] = {}


def file_erreur(nom: str) -> str:
    return f"{nom}.dlq"


async def traiter_une_fois(
    sessions: async_sessionmaker[AsyncSession],
    nom: str,
    traitement: Traitement,
    evenement: Evenement,
    apres_commit: ApresCommit | None = None,
) -> bool:
    """Une livraison : inscrit le message dans `messages_traites` et lance le traitement dans la
    même transaction ; un message déjà traité n'a aucun effet. Après le commit, lance
    `apres_commit` (aussi pour un message déjà traité : l'action doit être idempotente).

    Renvoie vrai si le traitement a tourné. Une exception du traitement annule la transaction
    et remonte ; `apres_commit` n'est alors pas lancé.

    `apres_commit` est au mieux (best effort) : son exception est journalisée (`WARNING`) et
    n'est pas propagée. La propager remettrait en file un message déjà commité : le rejeu
    serait sans effet métier (messages_traites), mais chaque échec compterait une livraison et
    finirait par envoyer en DLQ un message traité avec succès. L'action doit donc tolérer de
    ne pas être faite (verrous Redis : ils expirent d'eux-mêmes).
    """
    with correlation(evenement.correlation_id):
        async with sessions() as session, session.begin():
            nouveau = await session.execute(
                insert(MESSAGES_TRAITES)
                .values(consommateur=nom, message_id=evenement.id)
                .on_conflict_do_nothing()
                .returning(MESSAGES_TRAITES.c.message_id)
            )
            traite = nouveau.first() is not None
            if traite:
                await traitement(session, evenement)
            else:
                journal.info("Message %s déjà traité par %s, ignoré", evenement.id, nom)
        if apres_commit is not None:
            try:
                await apres_commit(evenement)
            except Exception:
                journal.warning(
                    "Action après commit en échec pour le message %s (%s), ignorée",
                    evenement.id,
                    nom,
                    exc_info=True,
                )
    return traite


def consommateur_idempotent(
    broker: RabbitBroker,
    sessions: async_sessionmaker[AsyncSession],
    *,
    nom: str,
    type_evenement: str,
    tentatives: int = TENTATIVES,
    apres_commit: ApresCommit | None = None,
) -> Callable[[Traitement], Traitement]:
    """Abonne le traitement à `type_evenement` sur la file durable `nom`.

    `apres_commit` (facultatif) : action lancée après le commit (voir `traiter_une_fois`).
    """
    file = RabbitQueue(
        nom,
        queue_type=QueueType.QUORUM,
        durable=True,
        routing_key=type_evenement,
        arguments={
            # Nombre de remises en file autorisées : la livraison n° tentatives part en DLQ.
            "x-delivery-limit": tentatives - 1,
            "x-dead-letter-exchange": EXCHANGE_ERREURS.name,
            "x-dead-letter-routing-key": file_erreur(nom),
        },
    )
    _files_erreur.setdefault(id(broker), []).append(
        RabbitQueue(
            file_erreur(nom),
            queue_type=QueueType.QUORUM,
            durable=True,
            routing_key=file_erreur(nom),
        )
    )

    def decorer(traitement: Traitement) -> Traitement:
        # NACK_ON_ERROR : une exception remet le message en file (requeue), ce qui compte une
        # livraison de plus pour la quorum queue.
        @broker.subscriber(file, EXCHANGE_TICKETING, ack_policy=AckPolicy.NACK_ON_ERROR)
        async def recevoir(evenement: Evenement) -> None:
            await traiter_une_fois(sessions, nom, traitement, evenement, apres_commit)

        return traitement

    return decorer


@asynccontextmanager
async def messagerie(broker: RabbitBroker) -> AsyncIterator[RabbitBroker]:
    """Connecte le broker, déclare l'exchange `ticketing` et les files d'erreur, puis démarre
    les consommateurs. Les DLQ existent ainsi avant le premier message en échec : un message
    envoyé vers une file absente serait perdu."""
    await broker.connect()
    await broker.declare_exchange(EXCHANGE_TICKETING)
    erreurs = await broker.declare_exchange(EXCHANGE_ERREURS)
    for file in _files_erreur.get(id(broker), []):
        declaree = await broker.declare_queue(file)
        await declaree.bind(erreurs, routing_key=file.routing_key)
    await broker.start()
    try:
        yield broker
    finally:
        await broker.stop()
