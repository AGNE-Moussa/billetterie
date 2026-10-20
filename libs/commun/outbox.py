"""Transactional Outbox : aucun événement perdu après une écriture en base.

Le code métier n'écrit jamais sur RabbitMQ. Il range l'événement dans la table `outbox` avec
`publier_plus_tard`, dans la même transaction que son écriture : les deux réussissent ou
échouent ensemble. Le `RelaisOutbox`, tâche de fond de chaque instance, publie ensuite les
lignes en attente sur l'exchange `ticketing` et les marque envoyées. Broker arrêté : les lignes
attendent et partent à son retour.

La livraison est « au moins une fois » (un arrêt entre la publication et le marquage republie la
ligne) : les consommateurs sont idempotents (commun.consommateurs).

Dans un service :

    # infra/base.py : les tables de messagerie rejoignent les migrations du service
    # alembic/env.py : target_metadata = [Base.metadata, METADONNEES_MESSAGERIE]
    # migration : creer_tables_messagerie()

    async with session.begin():
        session.add(commande)
        await publier_plus_tard(session, Evenement.creer("ticketing.order.confirmed", {...}))
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import sqlalchemy as sa
from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commun.evenements import EXCHANGE, Evenement

journal = logging.getLogger(__name__)

INTERVALLE_RELAIS = 0.5
TAILLE_LOT = 100
DELAI_PUBLICATION = 5.0

EXCHANGE_TICKETING = RabbitExchange(EXCHANGE, type=ExchangeType.TOPIC, durable=True)

# Tables communes à tous les services, ajoutées à leurs migrations.
METADONNEES_MESSAGERIE = sa.MetaData()

OUTBOX = sa.Table(
    "outbox",
    METADONNEES_MESSAGERIE,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("type", sa.String(200), nullable=False),
    sa.Column("version", sa.Integer(), nullable=False),
    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("correlation_id", sa.String(128)),
    sa.Column("data", JSONB(), nullable=False),
    sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column("envoye_le", sa.DateTime(timezone=True)),
    # Le relais ne lit que les lignes en attente, dans l'ordre d'écriture.
    sa.Index("ix_outbox_en_attente", "cree_le", postgresql_where=sa.text("envoye_le IS NULL")),
)

MESSAGES_TRAITES = sa.Table(
    "messages_traites",
    METADONNEES_MESSAGERIE,
    sa.Column("consommateur", sa.String(200), primary_key=True),
    sa.Column("message_id", sa.Uuid(), primary_key=True),
    sa.Column(
        "traite_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    ),
)


def creer_tables_messagerie() -> None:
    """À appeler dans `upgrade()` d'une migration Alembic du service (migration type)."""
    from alembic import op

    for table in (OUTBOX, MESSAGES_TRAITES):
        table.create(op.get_bind())


def supprimer_tables_messagerie() -> None:
    """À appeler dans `downgrade()` de la même migration."""
    from alembic import op

    for table in (MESSAGES_TRAITES, OUTBOX):
        table.drop(op.get_bind())


async def publier_plus_tard(session: AsyncSession, evenement: Evenement) -> None:
    """Range l'événement dans l'outbox, dans la transaction en cours de la session."""
    await session.execute(
        insert(OUTBOX).values(
            id=evenement.id,
            type=evenement.type,
            version=evenement.version,
            occurred_at=evenement.occurred_at,
            correlation_id=evenement.correlation_id,
            data=evenement.data,
        )
    )


class RelaisOutbox:
    """Publie les lignes en attente de l'outbox, puis les marque envoyées.

    Plusieurs instances peuvent tourner : `FOR UPDATE SKIP LOCKED` réserve chaque lot à une
    seule d'entre elles. Un échec de publication arrête le lot (l'ordre est conservé) ; les
    lignes déjà confirmées par le broker sont marquées.

    Le relais se connecte lui-même au broker, et réessaie à chaque passe : un service démarre
    et écrit même si RabbitMQ est absent, ses événements partent à son arrivée.
    """

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        broker: RabbitBroker,
        intervalle: float = INTERVALLE_RELAIS,
        taille_lot: int = TAILLE_LOT,
    ) -> None:
        self._sessions = sessions
        self._broker = broker
        self._intervalle = intervalle
        self._taille_lot = taille_lot
        self._pret = False
        # Une panne du broker est journalisée à son début et à sa fin, pas à chaque passe.
        self._en_panne = False

    async def _preparer(self) -> bool:
        """Connexion au broker et déclaration de l'exchange, une fois ; False si impossible."""
        if not self._pret:
            try:
                await self._broker.connect()
                await self._broker.declare_exchange(EXCHANGE_TICKETING)
            except Exception:
                self._signaler_panne("Broker injoignable, nouvel essai plus tard")
                return False
            self._pret = True
        return True

    async def publier_en_attente(self) -> int:
        """Une passe du relais ; renvoie le nombre d'événements publiés."""
        if not await self._preparer():
            return 0
        publies = 0
        async with self._sessions() as session, session.begin():
            requete = (
                sa.select(OUTBOX)
                .where(OUTBOX.c.envoye_le.is_(None))
                .order_by(OUTBOX.c.cree_le)
                .limit(self._taille_lot)
                .with_for_update(skip_locked=True)
            )
            for ligne in (await session.execute(requete)).mappings():
                evenement = Evenement(
                    id=ligne["id"],
                    type=ligne["type"],
                    version=ligne["version"],
                    occurred_at=ligne["occurred_at"],
                    correlation_id=ligne["correlation_id"],
                    data=ligne["data"],
                )
                try:
                    await self._publier(evenement)
                except Exception:
                    self._signaler_panne("Publication impossible, événements gardés dans l'outbox")
                    break
                if self._en_panne:
                    self._en_panne = False
                    journal.warning("Publication rétablie, envoi des événements en attente")
                await session.execute(
                    sa.update(OUTBOX)
                    .where(OUTBOX.c.id == evenement.id)
                    .values(envoye_le=sa.func.now())
                )
                publies += 1
        return publies

    def _signaler_panne(self, message: str) -> None:
        if self._en_panne:
            journal.debug(message, exc_info=True)
        else:
            self._en_panne = True
            journal.warning(message, exc_info=True)

    async def _publier(self, evenement: Evenement) -> None:
        # Attend la confirmation du broker (publisher confirms) : une ligne n'est marquée
        # envoyée qu'une fois le message enregistré par RabbitMQ.
        await self._broker.publish(
            evenement.model_dump(mode="json"),
            exchange=EXCHANGE_TICKETING,
            routing_key=evenement.type,
            persist=True,
            message_id=str(evenement.id),
            correlation_id=evenement.correlation_id,
            message_type=evenement.type,
            timeout=DELAI_PUBLICATION,
        )

    async def tourner(self) -> None:
        while True:
            try:
                publies = await self.publier_en_attente()
            except Exception:
                # Base momentanément absente : le relais réessaie au tour suivant.
                journal.warning("Passe du relais de l'outbox en échec", exc_info=True)
                publies = 0
            # Lot plein : il reste sans doute des lignes, on enchaîne sans attendre.
            if publies < self._taille_lot:
                await asyncio.sleep(self._intervalle)

    @asynccontextmanager
    async def en_fond(self) -> AsyncIterator[None]:
        """Lance le relais pendant le bloc (lifespan du service), l'arrête à la sortie."""
        tache = asyncio.create_task(self.tourner(), name="relais-outbox")
        try:
            yield
        finally:
            tache.cancel()
            with suppress(asyncio.CancelledError):
                await tache
