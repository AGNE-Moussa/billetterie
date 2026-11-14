"""Consultation des billets par leur acheteur (BIL-021, Q2, Q3 et Q6 de BIL-018).

Toute lecture filtre par l'appelant du jeton (`Appelant.identifiant`, le `sub` Keycloak gardé
dans `billets.client`), jamais par un paramètre fourni par le client. Un billet d'un autre
appelant répond comme un billet inexistant : 404 TICKET_NOT_FOUND, jamais 403.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from billets.domaine.places import PageResultat
from commun.auth import Appelant
from commun.erreurs import ErreurMetier


class StatutBillet(StrEnum):
    EMIS = "EMIS"
    ANNULE = "ANNULE"


# Description du schéma StatutBillet du contrat (Pydantic la lit dans __doc__).
StatutBillet.__doc__ = (
    "ANNULE quand la séance est annulée (consommateur de ticketing.show.cancelled)."
)


@dataclass(frozen=True)
class BilletLu:
    """Billet de l'appelant, avec le rang et le numéro de sa place (table places)."""

    id: UUID
    commande_id: UUID
    seance_id: UUID
    place_id: UUID
    rang: str
    numero: int
    statut: StatutBillet
    qr_code: str
    emis_le: datetime


class BilletIntrouvable(ErreurMetier):
    """Billet inconnu ou d'un autre appelant : 404, jamais 403."""

    def __init__(self, billet_id: UUID) -> None:
        super().__init__(
            "TICKET_NOT_FOUND",
            404,
            f"Aucun billet avec l'identifiant {billet_id}.",
            titre="Billet introuvable",
        )


class DepotBillets(Protocol):
    """Lecture des billets ; lève `BaseIndisponible` (503) si la base ne répond pas.

    Toute lecture filtre par `client`.
    """

    async def lister_billets(
        self, client: str, commande_id: UUID | None, page: int, size: int
    ) -> PageResultat[BilletLu]:
        """Billets du client (de la commande si `commande_id`), par émission décroissante
        puis identifiant."""
        ...

    async def lire_billet(self, client: str, billet_id: UUID) -> BilletLu | None:
        """Le billet du client, ou None (inconnu ou d'un autre client)."""
        ...


async def lister_billets(
    depot: DepotBillets, appelant: Appelant, commande_id: UUID | None, page: int, size: int
) -> PageResultat[BilletLu]:
    """Page des billets de l'appelant, restreinte à une commande si `commande_id` est fourni."""
    return await depot.lister_billets(appelant.identifiant, commande_id, page, size)


async def lire_billet(depot: DepotBillets, appelant: Appelant, billet_id: UUID) -> BilletLu:
    """Le billet de l'appelant ; lève `BilletIntrouvable` sinon."""
    billet = await depot.lire_billet(appelant.identifiant, billet_id)
    if billet is None:
        raise BilletIntrouvable(billet_id)
    return billet
