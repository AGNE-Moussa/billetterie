"""Ports des services appelés par Commandes : Billets, Catalogue, Paiements.

Le domaine ne connaît que ces ports ; `infra/clients.py` les réalise avec
`commun.http.ClientService` (jeton de service, corrélation, disjoncteur) et les tests unitaires
avec un `ClientService` sur `httpx.MockTransport`. Chaque méthode lève
`commun.http.ServiceIndisponible` (503 SERVICE_INDISPONIBLE) si la cible ne répond pas.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class SeanceLue:
    """Séance lue dans Catalogue (`lireSeanceParId`), réduite à ce qu'utilise Commandes."""

    id: UUID
    debut: datetime
    annulee: bool
    # Prix en centimes de chaque catégorie de places de la séance, par identifiant.
    prix_par_categorie: dict[UUID, int]


@dataclass(frozen=True)
class VerrouPlace:
    """Réponse `Verrou` de Billets (`verrouillerPlace`)."""

    place_id: UUID
    seance_id: UUID
    categorie_id: UUID
    commande_id: UUID
    expire_le: datetime


@dataclass(frozen=True)
class PaiementEnregistre:
    """Réponse `Paiement` (201) de Paiements (`creerPaiement`)."""

    id: UUID
    commande_id: UUID
    seance_id: UUID
    montant: int


@dataclass(frozen=True)
class PaiementLu:
    """Réponse `Paiement` (200) de Paiements (`lirePaiement`), réduite à ce qu'utilise
    Commandes : son statut (`ACCEPTE`, `REFUSE` ou `REMBOURSE`)."""

    commande_id: UUID
    statut: str


class ClientCatalogue(Protocol):
    async def lire_seance(self, seance_id: UUID) -> SeanceLue | None:
        """La séance, ou None si Catalogue répond 404 (SHOW_NOT_FOUND)."""
        ...


class ClientBillets(Protocol):
    async def verrouiller_place(
        self, place_id: UUID, *, seance_id: UUID, commande_id: UUID, confirmation: bool
    ) -> VerrouPlace:
        """`PUT /api/v1/seats/{place_id}/lock` ; lève `PlaceDejaPrise` (409) ou
        `PlaceIntrouvable` (404)."""
        ...


class ClientPaiements(Protocol):
    async def payer(
        self, *, commande_id: UUID, seance_id: UUID, montant: int, carte_test: str
    ) -> PaiementEnregistre:
        """`POST /api/v1/payments` avec `Idempotency-Key` = `commande_id` ; lève
        `PaiementRefuse` (402), `SeanceAnnulee` (409 SHOW_CANCELLED) ou
        `PaiementDejaExistant` (409 PAYMENT_ALREADY_EXISTS)."""
        ...

    async def lire(self, commande_id: UUID) -> PaiementLu | None:
        """`GET /api/v1/payments/{commande_id}`, lecture sans effet (jamais de débit) ; None si
        Paiements répond 404 (PAYMENT_NOT_FOUND)."""
        ...
