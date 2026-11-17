"""Consommateurs d'événements du service commandes (BIL-011).

- `commandes.show-cancelled` : expire les commandes `EN_ATTENTE` de la séance annulée (Q5, H1).
- `commandes.payment-refunded` : passe la commande remboursée `REMBOURSEE`, ou `EXPIREE` si elle
  était encore `EN_ATTENTE` (Q4).

Chaque traitement écrit, avec ses `ticketing.order.expired`, dans la transaction qui inscrit le
message dans `messages_traites` (commun.consommateurs) ; une exception donne trois tentatives,
puis `<nom>.dlq`.
"""

import logging

from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commandes.domaine.annulation import (
    CONSOMMATEUR_PAIEMENT_REMBOURSE,
    CONSOMMATEUR_SEANCE_ANNULEE,
    EVENEMENT_PAIEMENT_REMBOURSE,
    EVENEMENT_SEANCE_ANNULEE,
    enregistrer_remboursement,
    expirer_commandes_de_la_seance,
)
from commandes.infra.depot import DepotAnnulationSql
from commun.consommateurs import consommateur_idempotent
from commun.evenements import Evenement

journal = logging.getLogger(__name__)


async def expirer_commandes_de_la_seance_annulee(
    session: AsyncSession, evenement: Evenement
) -> None:
    """Traitement de ticketing.show.cancelled."""
    expirees = await expirer_commandes_de_la_seance(DepotAnnulationSql(session), evenement.data)
    journal.info(
        "Séance %s annulée : %d commandes en attente expirées (message %s)",
        evenement.data.get("seance_id"),
        expirees,
        evenement.id,
    )


async def enregistrer_paiement_rembourse(session: AsyncSession, evenement: Evenement) -> None:
    """Traitement de ticketing.payment.refunded."""
    statut = await enregistrer_remboursement(DepotAnnulationSql(session), evenement.data)
    if statut is not None:
        journal.info(
            "Commande %s passée %s après remboursement (message %s)",
            evenement.data.get("commande_id"),
            statut.value,
            evenement.id,
        )


def abonner_consommateurs(broker: RabbitBroker, sessions: async_sessionmaker[AsyncSession]) -> None:
    """Abonne les traitements du service au broker, avant `commun.consommateurs.messagerie`."""
    consommateur_idempotent(
        broker,
        sessions,
        nom=CONSOMMATEUR_SEANCE_ANNULEE,
        type_evenement=EVENEMENT_SEANCE_ANNULEE,
    )(expirer_commandes_de_la_seance_annulee)
    consommateur_idempotent(
        broker,
        sessions,
        nom=CONSOMMATEUR_PAIEMENT_REMBOURSE,
        type_evenement=EVENEMENT_PAIEMENT_REMBOURSE,
    )(enregistrer_paiement_rembourse)
