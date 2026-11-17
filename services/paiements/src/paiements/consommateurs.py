"""Consommateurs d'événements du service paiements (BIL-011, CA1).

- `paiements.show-cancelled` : rembourse les paiements `ACCEPTE` de la séance annulée.
- `paiements.ticket-rejected` : rembourse le paiement de la commande refusée par Billets (Q1).

Chaque traitement écrit, avec ses `ticketing.payment.refunded`, dans la transaction qui inscrit
le message dans `messages_traites` (commun.consommateurs) ; une exception donne trois
tentatives, puis `<nom>.dlq`.
"""

import logging
from datetime import UTC, datetime

from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commun.consommateurs import consommateur_idempotent
from commun.evenements import Evenement
from paiements.domaine.remboursements import (
    CONSOMMATEUR_BILLETS_REFUSES,
    CONSOMMATEUR_SEANCE_ANNULEE,
    EVENEMENT_BILLETS_REFUSES,
    EVENEMENT_SEANCE_ANNULEE,
    rembourser_commande_refusee,
    rembourser_seance,
)
from paiements.infra.depot import DepotRemboursementsSql

journal = logging.getLogger(__name__)


async def rembourser_paiements_de_la_seance(session: AsyncSession, evenement: Evenement) -> None:
    """Traitement de ticketing.show.cancelled."""
    rembourses = await rembourser_seance(
        DepotRemboursementsSql(session), evenement.data, annulee_le=datetime.now(UTC)
    )
    journal.info(
        "Séance %s annulée : %d paiements remboursés (message %s)",
        evenement.data.get("seance_id"),
        len(rembourses),
        evenement.id,
    )


async def rembourser_paiement_de_la_commande(session: AsyncSession, evenement: Evenement) -> None:
    """Traitement de ticketing.ticket.rejected."""
    rembourse = await rembourser_commande_refusee(DepotRemboursementsSql(session), evenement.data)
    if rembourse is None:
        journal.info(
            "Commande %s refusée par Billets : aucun paiement accepté à rembourser (message %s)",
            evenement.data.get("commande_id"),
            evenement.id,
        )
        return
    journal.info(
        "Commande %s refusée par Billets : paiement %s remboursé (message %s)",
        rembourse.commande_id,
        rembourse.id,
        evenement.id,
    )


def abonner_consommateurs(broker: RabbitBroker, sessions: async_sessionmaker[AsyncSession]) -> None:
    """Abonne les traitements du service au broker, avant `commun.consommateurs.messagerie`."""
    consommateur_idempotent(
        broker,
        sessions,
        nom=CONSOMMATEUR_SEANCE_ANNULEE,
        type_evenement=EVENEMENT_SEANCE_ANNULEE,
    )(rembourser_paiements_de_la_seance)
    consommateur_idempotent(
        broker,
        sessions,
        nom=CONSOMMATEUR_BILLETS_REFUSES,
        type_evenement=EVENEMENT_BILLETS_REFUSES,
    )(rembourser_paiement_de_la_commande)
