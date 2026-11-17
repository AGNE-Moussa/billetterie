"""Remboursements simulés (BIL-011, CA1) : règles métier, sans SQLAlchemy.

- `ticketing.show.cancelled` : inscrit la séance dans `seances_annulees` et rembourse chaque
  paiement `ACCEPTE` de la séance, sous le verrou consultatif exclusif de la séance (Q2) ;
  `creerPaiement` le prend en partagé.
- `ticketing.ticket.rejected` (Q1) : rembourse le paiement `ACCEPTE` de la commande refusée.

Tout passage `ACCEPTE` → `REMBOURSE` est conditionnel au statut courant et publie un
`ticketing.payment.refunded` par paiement, dans la même transaction (H5, H6) : un paiement
n'est remboursé qu'une fois, quelles que soient les sources et leur ordre.
"""

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from commun.evenements import Evenement
from paiements.domaine.paiements import Paiement

EVENEMENT_SEANCE_ANNULEE = "ticketing.show.cancelled"
EVENEMENT_BILLETS_REFUSES = "ticketing.ticket.rejected"
# Publié par l'outbox, un par paiement remboursé.
EVENEMENT_PAIEMENT_REMBOURSE = "ticketing.payment.refunded"
# Files durables des consommateurs (messages_traites.consommateur, DLQ <nom>.dlq), H5.
CONSOMMATEUR_SEANCE_ANNULEE = "paiements.show-cancelled"
CONSOMMATEUR_BILLETS_REFUSES = "paiements.ticket-rejected"


class DonneesInvalides(ValueError):
    """`data` d'un événement inexploitable : trois tentatives, puis file d'erreur."""


class DepotRemboursements(Protocol):
    """Séances annulées et remboursements, dans la transaction du consommateur."""

    async def verrouiller_seance(self, seance_id: UUID) -> None:
        """Verrou consultatif exclusif de la séance, jusqu'à la fin de la transaction (Q2)."""
        ...

    async def inscrire_seance_annulee(self, seance_id: UUID, annulee_le: datetime) -> bool:
        """Inscrit la séance dans `seances_annulees` (ON CONFLICT DO NOTHING) ; faux si elle y
        figurait déjà."""
        ...

    async def rembourser_paiements_de_la_seance(self, seance_id: UUID) -> list[Paiement]:
        """Passe les paiements `ACCEPTE` de la séance en `REMBOURSE` ; renvoie ceux que cet
        appel a fait passer."""
        ...

    async def rembourser_paiement_de_la_commande(self, commande_id: UUID) -> Paiement | None:
        """Passe le paiement de la commande en `REMBOURSE` s'il est `ACCEPTE` ; renvoie le
        paiement remboursé par cet appel, ou None."""
        ...

    async def publier(self, evenement: Evenement) -> None:
        """Range l'événement dans l'outbox, dans la transaction en cours."""
        ...


def donnees_paiement_rembourse(paiement: Paiement) -> dict[str, Any]:
    """`data` de ticketing.payment.refunded v1 : `paiement_id`, `commande_id`, `seance_id`,
    `montant` du paiement (H6)."""
    return {
        "paiement_id": str(paiement.id),
        "commande_id": str(paiement.commande_id),
        "seance_id": str(paiement.seance_id),
        "montant": paiement.montant,
    }


def _identifiant(data: dict[str, Any], champ: str, evenement: str) -> UUID:
    try:
        return UUID(str(data[champ]))
    except (KeyError, TypeError, ValueError) as erreur:
        raise DonneesInvalides(f"{evenement} invalide : {erreur!r}") from erreur


async def _publier_remboursements(depot: DepotRemboursements, paiements: list[Paiement]) -> None:
    for paiement in paiements:
        await depot.publier(
            Evenement.creer(EVENEMENT_PAIEMENT_REMBOURSE, donnees_paiement_rembourse(paiement))
        )


async def rembourser_seance(
    depot: DepotRemboursements, data: dict[str, Any], *, annulee_le: datetime
) -> list[Paiement]:
    """Traitement de ticketing.show.cancelled ; renvoie les paiements remboursés par cet appel.
    Lève `DonneesInvalides`."""
    seance_id = _identifiant(data, "seance_id", EVENEMENT_SEANCE_ANNULEE)
    _identifiant(data, "evenement_id", EVENEMENT_SEANCE_ANNULEE)
    # Exclusif : attend les paiements en cours de la séance (partagé), qui seront donc écrits
    # et remboursés ci-dessous ; ceux qui arrivent après liront la séance annulée (Q2).
    await depot.verrouiller_seance(seance_id)
    await depot.inscrire_seance_annulee(seance_id, annulee_le)
    # Toujours repassé, même séance déjà inscrite : le passage ne touche que les `ACCEPTE`.
    rembourses = await depot.rembourser_paiements_de_la_seance(seance_id)
    await _publier_remboursements(depot, rembourses)
    return rembourses


async def rembourser_commande_refusee(
    depot: DepotRemboursements, data: dict[str, Any]
) -> Paiement | None:
    """Traitement de ticketing.ticket.rejected (Q1), quel que soit le motif ; renvoie le
    paiement remboursé par cet appel, ou None. Lève `DonneesInvalides`."""
    commande_id = _identifiant(data, "commande_id", EVENEMENT_BILLETS_REFUSES)
    rembourse = await depot.rembourser_paiement_de_la_commande(commande_id)
    if rembourse is not None:
        await _publier_remboursements(depot, [rembourse])
    return rembourse
