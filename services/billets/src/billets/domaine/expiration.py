"""Libération des places d'une commande expirée (BIL-010), sans SQLAlchemy ni Redis.

`ticketing.order.expired` : Billets supprime le verrou de chaque place de la commande, seulement
s'il est encore détenu par elle (comparer puis supprimer, `MagasinVerrous.liberer`, H5) ; le
champ `remboursement_du` est ignoré. La libération a lieu dans le traitement (décision Q3) :
Redis injoignable lève `VerrouIndisponible`, d'où trois tentatives puis
`billets.order-expired.dlq` ; un rejeu relibère sans effet.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from billets.domaine.verrous import MagasinVerrous

# Consommé pour libérer les places (docs/evenements/ticketing.order.expired.json).
EVENEMENT_COMMANDE_EXPIREE = "ticketing.order.expired"
# File durable du consommateur (messages_traites.consommateur, DLQ billets.order-expired.dlq).
CONSOMMATEUR_COMMANDE_EXPIREE = "billets.order-expired"


@dataclass(frozen=True)
class CommandeExpiree:
    """`data` de ticketing.order.expired, utile à Billets."""

    commande_id: UUID
    seance_id: UUID
    place_ids: tuple[UUID, ...]


class DonneesExpirationInvalides(ValueError):
    """`data` de ticketing.order.expired inexploitable : le message part en file d'erreur après
    trois tentatives (commun.consommateurs)."""


def commande_expiree(data: dict[str, Any]) -> CommandeExpiree:
    """Lit `data` de ticketing.order.expired ; lève `DonneesExpirationInvalides`."""
    try:
        commande_id = UUID(str(data["commande_id"]))
        seance_id = UUID(str(data["seance_id"]))
        brutes = data["place_ids"]
        if not isinstance(brutes, list):
            raise TypeError("place_ids n'est pas une liste")
        place_ids = tuple(UUID(str(place_id)) for place_id in brutes)
    except (KeyError, TypeError, ValueError) as erreur:
        raise DonneesExpirationInvalides(f"Commande expirée invalide : {erreur!r}") from erreur
    if not place_ids:
        raise DonneesExpirationInvalides("Commande expirée invalide : aucune place")
    return CommandeExpiree(commande_id=commande_id, seance_id=seance_id, place_ids=place_ids)


async def liberer_places_expirees(verrous: MagasinVerrous, data: dict[str, Any]) -> None:
    """Supprime les verrous des places encore détenus par la commande expirée.

    Lève `DonneesExpirationInvalides` si `data` est inexploitable, `VerrouIndisponible` si
    Redis ne répond pas.
    """
    commande = commande_expiree(data)
    for place_id in commande.place_ids:
        # Comparer puis supprimer d'un bloc (script Lua) : le verrou d'une autre commande reste.
        await verrous.liberer(commande.seance_id, place_id, commande.commande_id)
