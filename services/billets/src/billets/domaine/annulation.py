"""Annulation d'une séance côté Billets (BIL-011, CA3) : règles métier, sans SQLAlchemy.

`ticketing.show.cancelled` inscrit la séance dans `seances_annulees` et passe ses billets
`EMIS` au statut `ANNULE` (H4 : places et billets gardés, `uq_billets_place` inchangée), sous le
verrou consultatif exclusif de la séance ; l'émission le prend en partagé (Q3).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

# Consommé pour invalider les billets de la séance.
EVENEMENT_SEANCE_ANNULEE = "ticketing.show.cancelled"
# File durable du consommateur (messages_traites.consommateur, DLQ billets.show-cancelled.dlq).
CONSOMMATEUR_SEANCE_ANNULEE = "billets.show-cancelled"

STATUT_ANNULE = "ANNULE"


@dataclass(frozen=True)
class SeanceAnnulee:
    """`data` de ticketing.show.cancelled v1."""

    seance_id: UUID
    evenement_id: UUID


class DonneesAnnulationInvalides(ValueError):
    """`data` de ticketing.show.cancelled inexploitable : trois tentatives, puis file d'erreur."""


class DepotAnnulation(Protocol):
    """Séances annulées et billets, dans la transaction du consommateur."""

    async def verrouiller_seance(self, seance_id: UUID) -> None:
        """Verrou consultatif exclusif de la séance, jusqu'à la fin de la transaction (Q3)."""
        ...

    async def inscrire_seance_annulee(self, seance_id: UUID, annulee_le: datetime) -> bool:
        """Inscrit la séance dans `seances_annulees` (ON CONFLICT DO NOTHING) ; faux si elle y
        figurait déjà (`annulee_le` d'origine conservée)."""
        ...

    async def annuler_billets(self, seance_id: UUID) -> int:
        """Passe les billets `EMIS` de la séance en `ANNULE` ; renvoie leur nombre."""
        ...


def seance_annulee(data: dict[str, Any]) -> SeanceAnnulee:
    """Lit `data` de ticketing.show.cancelled ; lève `DonneesAnnulationInvalides`."""
    try:
        return SeanceAnnulee(
            seance_id=UUID(str(data["seance_id"])),
            evenement_id=UUID(str(data["evenement_id"])),
        )
    except (KeyError, TypeError, ValueError) as erreur:
        raise DonneesAnnulationInvalides(f"Séance annulée invalide : {erreur!r}") from erreur


async def annuler_seance(
    depot: DepotAnnulation, data: dict[str, Any], *, annulee_le: datetime
) -> int:
    """Traitement de ticketing.show.cancelled : verrou exclusif, inscription de la séance, puis
    billets `ANNULE` ; renvoie le nombre de billets annulés (idempotent)."""
    annulee = seance_annulee(data)
    # Exclusif : attend la fin des émissions en cours de la séance ; celles qui arrivent après
    # liront la séance annulée (Q3).
    await depot.verrouiller_seance(annulee.seance_id)
    await depot.inscrire_seance_annulee(annulee.seance_id, annulee_le)
    # Toujours repassé, même séance déjà inscrite : le passage ne touche que les billets `EMIS`.
    return await depot.annuler_billets(annulee.seance_id)
