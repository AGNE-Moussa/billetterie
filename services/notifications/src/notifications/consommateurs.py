"""Consommateurs d'événements du service notifications (BIL-009).

- `notifications.order-confirmed` : enregistre le destinataire de la commande.
- `notifications.ticket-issued` : envoie l'e-mail du billet, une seule fois (historique
  `envois`, CA3).

Chaque traitement écrit dans la transaction qui inscrit le message dans `messages_traites`
(commun.consommateurs) ; une exception donne trois tentatives, puis `<nom>.dlq`.
"""

from datetime import UTC, datetime

from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commun.consommateurs import Traitement, consommateur_idempotent
from commun.evenements import Evenement
from notifications.domaine.envois import (
    CONSOMMATEUR_BILLET_EMIS,
    CONSOMMATEUR_COMMANDE_CONFIRMEE,
    EVENEMENT_BILLET_EMIS,
    EVENEMENT_COMMANDE_CONFIRMEE,
    Envoyeur,
    enregistrer_destinataire,
    envoyer_billet,
)
from notifications.infra.depot import DepotNotificationsSql


async def enregistrer_destinataire_de_commande(session: AsyncSession, evenement: Evenement) -> None:
    """Traitement de ticketing.order.confirmed."""
    await enregistrer_destinataire(DepotNotificationsSql(session), evenement)


def traitement_billet_emis(envoyeur: Envoyeur, expediteur: str) -> Traitement:
    """Traitement de ticketing.ticket.issued, lié à l'envoyeur et à l'expéditeur."""

    async def envoyer_e_mail_du_billet(session: AsyncSession, evenement: Evenement) -> None:
        await envoyer_billet(
            DepotNotificationsSql(session),
            envoyeur,
            evenement,
            expediteur=expediteur,
            maintenant=datetime.now(UTC),
        )

    return envoyer_e_mail_du_billet


def abonner_consommateurs(
    broker: RabbitBroker,
    sessions: async_sessionmaker[AsyncSession],
    envoyeur: Envoyeur,
    expediteur: str,
) -> None:
    """Abonne les traitements du service au broker, avant `commun.consommateurs.messagerie`."""
    consommateur_idempotent(
        broker,
        sessions,
        nom=CONSOMMATEUR_COMMANDE_CONFIRMEE,
        type_evenement=EVENEMENT_COMMANDE_CONFIRMEE,
    )(enregistrer_destinataire_de_commande)
    consommateur_idempotent(
        broker,
        sessions,
        nom=CONSOMMATEUR_BILLET_EMIS,
        type_evenement=EVENEMENT_BILLET_EMIS,
    )(traitement_billet_emis(envoyeur, expediteur))
