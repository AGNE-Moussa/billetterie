"""Paiements simulés : entités, erreurs métier, port du dépôt et cas d'usage, sans SQLAlchemy.

Aucune donnée de carte n'est conservée ni journalisée : seul le statut qui en découle l'est.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from commun.erreurs import ErreurMetier

# Carte de test refusée (décision Q5 de BIL-008) ; tout autre numéro de 16 chiffres est accepté.
CARTE_REFUSEE = "4000000000000002"


class StatutPaiement(StrEnum):
    ACCEPTE = "ACCEPTE"
    REFUSE = "REFUSE"
    REMBOURSE = "REMBOURSE"


@dataclass(frozen=True)
class Paiement:
    id: UUID
    # Idempotency-Key : un seul paiement par commande (décision Q6).
    commande_id: UUID
    seance_id: UUID
    montant: int
    statut: StatutPaiement
    cree_le: datetime


class PaiementRefuse(ErreurMetier):
    def __init__(self) -> None:
        super().__init__("PAYMENT_REFUSED", 402, "Le paiement est refusé.", titre="Paiement refusé")


class PaiementDejaExistant(ErreurMetier):
    def __init__(self, commande_id: UUID) -> None:
        super().__init__(
            "PAYMENT_ALREADY_EXISTS",
            409,
            f"Un paiement différent existe déjà pour la commande {commande_id}.",
            titre="Paiement déjà existant",
        )


class SeanceAnnulee(ErreurMetier):
    def __init__(self, seance_id: UUID) -> None:
        super().__init__(
            "SHOW_CANCELLED", 409, f"La séance {seance_id} est annulée.", titre="Séance annulée"
        )


class PaiementIntrouvable(ErreurMetier):
    def __init__(self, commande_id: UUID) -> None:
        super().__init__(
            "PAYMENT_NOT_FOUND",
            404,
            f"Aucun paiement pour la commande {commande_id}.",
            titre="Paiement introuvable",
        )


class CleIdempotenceInvalide(ErreurMetier):
    """Idempotency-Key différent de commande_id : 422 REQUETE_INVALIDE (contrat)."""

    def __init__(self) -> None:
        super().__init__(
            "REQUETE_INVALIDE",
            422,
            "L'en-tête Idempotency-Key doit être égal à commande_id.",
            titre="Requête invalide",
        )


class DepotPaiements(Protocol):
    """Accès aux paiements ; lève `BaseIndisponible` (503) si la base ne répond pas."""

    async def lire_par_commande(self, commande_id: UUID) -> Paiement | None:
        """Le paiement enregistré de la commande, ou None."""
        ...

    async def seance_annulee(self, seance_id: UUID) -> bool:
        """Vrai si la séance figure dans `seances_annulees` (décision Q9)."""
        ...

    async def inserer_ou_relire(self, paiement: Paiement) -> Paiement:
        """Insère le paiement s'il n'en existe aucun pour sa commande (`uq_paiements_commande_id`,
        ON CONFLICT DO NOTHING), puis renvoie le paiement enregistré (décision Q21)."""
        ...


async def payer(
    depot: DepotPaiements,
    maintenant: datetime,
    *,
    cle_idempotence: UUID,
    commande_id: UUID,
    seance_id: UUID,
    montant: int,
    carte_test: str,
) -> Paiement:
    """Paie la commande, ou rejoue le paiement enregistré ; renvoie un paiement ACCEPTE.

    Lève `CleIdempotenceInvalide` (422), `PaiementRefuse` (402, aussi au rejeu d'un refus),
    `PaiementDejaExistant` (409) ou `SeanceAnnulee` (409).
    """
    if cle_idempotence != commande_id:
        raise CleIdempotenceInvalide()
    # Un paiement déjà enregistré se rejoue d'abord, même si la séance a été annulée depuis
    # (décision Q20).
    enregistre = await depot.lire_par_commande(commande_id)
    if enregistre is None:
        if await depot.seance_annulee(seance_id):
            raise SeanceAnnulee(seance_id)
        # Refus simulé par la seule carte de test, jamais par un réglage global (décision Q5).
        statut = StatutPaiement.REFUSE if carte_test == CARTE_REFUSEE else StatutPaiement.ACCEPTE
        nouveau = Paiement(
            id=uuid4(),
            commande_id=commande_id,
            seance_id=seance_id,
            montant=montant,
            statut=statut,
            cree_le=maintenant,
        )
        # Requêtes simultanées : une seule insertion gagne, les autres relisent (décision Q21).
        enregistre = await depot.inserer_ou_relire(nouveau)
    return _rejouer(enregistre, seance_id=seance_id, montant=montant)


async def lire_paiement(depot: DepotPaiements, commande_id: UUID) -> Paiement:
    """Le paiement enregistré de la commande, quel que soit son statut ; lecture seule, ne crée
    jamais de paiement (review BIL-008, point 3). Lève `PaiementIntrouvable` (404)."""
    paiement = await depot.lire_par_commande(commande_id)
    if paiement is None:
        raise PaiementIntrouvable(commande_id)
    return paiement


def _rejouer(paiement: Paiement, *, seance_id: UUID, montant: int) -> Paiement:
    """Résultat enregistré d'une commande : même séance et même montant, sinon 409 (Q6)."""
    if (paiement.seance_id, paiement.montant) != (seance_id, montant):
        raise PaiementDejaExistant(paiement.commande_id)
    if paiement.statut is StatutPaiement.REFUSE:
        raise PaiementRefuse()
    return paiement
