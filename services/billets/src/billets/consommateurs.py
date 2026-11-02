"""Consommateurs d'événements du service billets.

`ticketing.show.scheduled` (décision Q5 de BIL-006) : crée les places de la séance, dans la
transaction qui inscrit le message dans `messages_traites` (commun.consommateurs). Un message
déjà traité est ignoré ; une séance déjà connue (autre message) ne crée aucun doublon
(`INSERT ... ON CONFLICT DO NOTHING`, décision Q18). Un `data` invalide lève une exception :
trois tentatives, puis `billets.show-scheduled.dlq`.
"""

import logging

from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from billets.domaine.places import (
    CONSOMMATEUR_SEANCE_PROGRAMMEE,
    EVENEMENT_SEANCE_PROGRAMMEE,
    places_de_la_seance,
)
from billets.infra.depot import DepotPlacesSql
from commun.consommateurs import consommateur_idempotent
from commun.evenements import Evenement

journal = logging.getLogger(__name__)


async def creer_places_de_la_seance(session: AsyncSession, evenement: Evenement) -> None:
    """Crée les places de la séance programmée (aucun doublon, aucune suppression)."""
    places = places_de_la_seance(evenement.data)
    await DepotPlacesSql(session).creer_places(places)
    # Lancé dans le bloc de corrélation du message : la ligne porte son correlation_id.
    journal.info(
        "Séance %s programmée : %d places reçues (message %s)",
        evenement.data.get("seance_id"),
        len(places),
        evenement.id,
    )


def abonner_consommateurs(broker: RabbitBroker, sessions: async_sessionmaker[AsyncSession]) -> None:
    """Abonne les traitements du service au broker, avant `commun.consommateurs.messagerie`."""
    consommateur_idempotent(
        broker,
        sessions,
        nom=CONSOMMATEUR_SEANCE_PROGRAMMEE,
        type_evenement=EVENEMENT_SEANCE_PROGRAMMEE,
    )(creer_places_de_la_seance)
