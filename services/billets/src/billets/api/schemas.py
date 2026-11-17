"""Corps des requêtes et des réponses (contrat services/billets/openapi.yaml)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from billets.domaine.consultation import StatutBillet
from commun.pagination import Page


class Sante(BaseModel):
    statut: str = Field(examples=["ok"])


class Place(BaseModel):
    id: UUID
    seance_id: UUID
    rang: str
    numero: int
    categorie_id: UUID = Field(description="Catégorie de places tarifée de la séance (Catalogue).")
    disponible: bool = Field(description="Faux si la place est verrouillée ou vendue.")


class PlacePage(Page[Place]):
    total: int = Field(description="Nombre total de places de la séance.")


class Billet(BaseModel):
    id: UUID
    commande_id: UUID
    seance_id: UUID
    place_id: UUID
    rang: str = Field(description="Rang de la place (table places).")
    numero: int = Field(description="Numéro de la place dans son rang (table places).")
    statut: StatutBillet
    qr_code: str = Field(
        description="Identifiant du billet signé (HMAC), jamais de donnée lisible."
    )
    emis_le: datetime


class BilletPage(Page[Billet]):
    total: int = Field(
        description=(
            "Nombre total de billets de l'appelant (de la commande si commande_id est fourni)."
        )
    )


class VerrouCreation(BaseModel):
    seance_id: UUID = Field(
        description=("Séance de la commande ; une place d'une autre séance répond SEAT_NOT_FOUND.")
    )
    commande_id: UUID = Field(description="Commande propriétaire du verrou.")
    confirmation: bool = Field(
        default=False,
        description=(
            "Faux, durée de réservation (10 min par défaut) ; vrai, durée de confirmation"
            " (1 h par défaut), seulement pour la commande qui détient le verrou."
        ),
    )


class Verrou(BaseModel):
    place_id: UUID
    seance_id: UUID
    categorie_id: UUID = Field(
        description=(
            "Catégorie de places tarifée de la séance (Catalogue), pour le prix de la ligne."
        )
    )
    commande_id: UUID
    expire_le: datetime = Field(
        description=(
            "Fin du verrou (réservation ou confirmation) ; la place est libérée ensuite si la"
            " commande n'est pas payée."
        )
    )
