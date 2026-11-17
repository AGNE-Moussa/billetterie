"""Annulation d'une séance et remboursements côté Commandes (BIL-011) : règles métier, sans
SQLAlchemy.

Le modèle de données l'emporte sur le libellé du ticket (H1) :

- `ticketing.show.cancelled` : chaque commande `EN_ATTENTE` de la séance (`expire_le` NULL
  compris) passe `EXPIREE` avec son `ticketing.order.expired` (toutes ses places, sans
  `remboursement_du`), sans appel à Paiements (Q5) ; une commande `CONFIRMEE` attend son
  remboursement.
- `ticketing.payment.refunded` : `CONFIRMEE` → `REMBOURSEE` ; `EN_ATTENTE` → `EXPIREE` avec
  `ticketing.order.expired` (Q4) ; `EXPIREE` ou `REMBOURSEE` : ignoré (`INFO`) ; commande
  inconnue : ignoré (`WARNING`, identifiant seul).

Tout passage relit la commande sous `FOR UPDATE` et dépend de son statut courant (H5).
"""

import logging
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from commandes.domaine.commandes import EVENEMENT_COMMANDE_EXPIREE, Commande, StatutCommande
from commun.evenements import Evenement

journal = logging.getLogger(__name__)

EVENEMENT_SEANCE_ANNULEE = "ticketing.show.cancelled"
EVENEMENT_PAIEMENT_REMBOURSE = "ticketing.payment.refunded"
# Files durables des consommateurs (messages_traites.consommateur, DLQ <nom>.dlq), H5.
CONSOMMATEUR_SEANCE_ANNULEE = "commandes.show-cancelled"
CONSOMMATEUR_PAIEMENT_REMBOURSE = "commandes.payment-refunded"


@dataclass(frozen=True)
class SeanceAnnulee:
    """`data` de ticketing.show.cancelled v1."""

    seance_id: UUID
    evenement_id: UUID


@dataclass(frozen=True)
class PaiementRembourse:
    """`data` de ticketing.payment.refunded v1."""

    paiement_id: UUID
    commande_id: UUID
    seance_id: UUID
    montant: int


class DonneesInvalides(ValueError):
    """`data` d'un événement inexploitable : trois tentatives, puis file d'erreur."""


class DepotAnnulation(Protocol):
    """Commandes de tous les clients, dans la transaction du consommateur."""

    async def commandes_en_attente_de_la_seance(self, seance_id: UUID) -> list[Commande]:
        """Commandes `EN_ATTENTE` de la séance, lignes verrouillées (`FOR UPDATE`) jusqu'à la
        fin de la transaction."""
        ...

    async def lire_commande_verrouillee(self, commande_id: UUID) -> Commande | None:
        """La commande, quel que soit son client, sous `FOR UPDATE` ; None si inconnue."""
        ...

    async def changer_statut(self, commande_id: UUID, statut: StatutCommande) -> None:
        """Nouveau statut de la commande."""
        ...

    async def publier(self, evenement: Evenement) -> None:
        """Range l'événement dans l'outbox, dans la transaction en cours."""
        ...


def seance_annulee(data: dict[str, Any]) -> SeanceAnnulee:
    """Lit `data` de ticketing.show.cancelled ; lève `DonneesInvalides`."""
    try:
        return SeanceAnnulee(
            seance_id=UUID(str(data["seance_id"])),
            evenement_id=UUID(str(data["evenement_id"])),
        )
    except (KeyError, TypeError, ValueError) as erreur:
        raise DonneesInvalides(f"Séance annulée invalide : {erreur!r}") from erreur


def paiement_rembourse(data: dict[str, Any]) -> PaiementRembourse:
    """Lit `data` de ticketing.payment.refunded ; lève `DonneesInvalides`."""
    try:
        montant = data["montant"]
        if isinstance(montant, bool) or not isinstance(montant, int):
            raise TypeError("montant entier attendu")
        return PaiementRembourse(
            paiement_id=UUID(str(data["paiement_id"])),
            commande_id=UUID(str(data["commande_id"])),
            seance_id=UUID(str(data["seance_id"])),
            montant=montant,
        )
    except (KeyError, TypeError, ValueError) as erreur:
        raise DonneesInvalides(f"Paiement remboursé invalide : {erreur!r}") from erreur


def _donnees_expiration(commande: Commande) -> dict[str, Any]:
    """`data` de ticketing.order.expired sans `remboursement_du` (Q5) : la commande, sa séance
    et toutes ses places."""
    return {
        "commande_id": str(commande.id),
        "seance_id": str(commande.seance_id),
        "place_ids": [str(ligne.place_id) for ligne in commande.lignes],
    }


async def _expirer(depot: DepotAnnulation, commande: Commande) -> None:
    await depot.changer_statut(commande.id, StatutCommande.EXPIREE)
    await depot.publier(Evenement.creer(EVENEMENT_COMMANDE_EXPIREE, _donnees_expiration(commande)))


async def expirer_commandes_de_la_seance(depot: DepotAnnulation, data: dict[str, Any]) -> int:
    """Traitement de ticketing.show.cancelled ; renvoie le nombre de commandes expirées par cet
    appel."""
    annulee = seance_annulee(data)
    # Lignes verrouillées par le dépôt et relues après toute transaction concurrente : une
    # commande confirmée ou expirée entre-temps n'est pas renvoyée (H5).
    commandes = await depot.commandes_en_attente_de_la_seance(annulee.seance_id)
    for commande in commandes:
        await _expirer(depot, commande)
    return len(commandes)


async def enregistrer_remboursement(
    depot: DepotAnnulation, data: dict[str, Any]
) -> StatutCommande | None:
    """Traitement de ticketing.payment.refunded ; renvoie le nouveau statut de la commande, ou
    None si rien n'a changé (commande inconnue, déjà `EXPIREE` ou `REMBOURSEE`)."""
    remboursement = paiement_rembourse(data)
    commande = await depot.lire_commande_verrouillee(remboursement.commande_id)
    if commande is None:
        # Identifiant seul dans le journal, jamais l'adresse de l'acheteur.
        journal.warning(
            "Remboursement du paiement %s pour la commande inconnue %s : ignoré",
            remboursement.paiement_id,
            remboursement.commande_id,
        )
        return None
    if commande.statut is StatutCommande.CONFIRMEE:
        await depot.changer_statut(commande.id, StatutCommande.REMBOURSEE)
        return StatutCommande.REMBOURSEE
    if commande.statut is StatutCommande.EN_ATTENTE:
        # Paiement accepté puis remboursé avant la confirmation (Q4) : la confirmation, gardée
        # par le statut EN_ATTENTE, échouera sans ticketing.order.confirmed.
        await _expirer(depot, commande)
        return StatutCommande.EXPIREE
    journal.info(
        "Remboursement du paiement %s : commande %s déjà %s, rien à changer",
        remboursement.paiement_id,
        commande.id,
        commande.statut.value,
    )
    return None
