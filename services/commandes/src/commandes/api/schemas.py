"""Corps des requêtes et des réponses (contrat services/commandes/openapi.yaml)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from commandes.domaine.commandes import StatutCommande
from commun.pagination import Page

# Taille maximale d'une commande (maxItems du contrat).
PLACES_PAR_COMMANDE_MAX = 10

DESCRIPTION_CARTE = (
    "Numéro de carte du paiement simulé, transmis à Paiements et jamais journalisé. Numéros"
    " de test : 4000000000000002 refusé (PAYMENT_REFUSED), tout autre numéro de 16 chiffres"
    " accepté (par exemple 4242424242424242)."
)
MOTIF_CARTE = r"^[0-9]{16}$"


class Sante(BaseModel):
    statut: str = Field(examples=["ok"])


class CommandeCreation(BaseModel):
    seance_id: UUID
    place_ids: list[UUID] = Field(
        min_length=1,
        max_length=PLACES_PAR_COMMANDE_MAX,
        json_schema_extra={"uniqueItems": True},
    )
    carte_test: str = Field(pattern=MOTIF_CARTE, description=DESCRIPTION_CARTE)

    @field_validator("place_ids")
    @classmethod
    def _places_distinctes(cls, place_ids: list[UUID]) -> list[UUID]:
        # uniqueItems du contrat : un doublon est refusé (422), jamais fusionné.
        if len(set(place_ids)) != len(place_ids):
            raise ValueError("Une place ne figure qu'une fois dans la commande.")
        return place_ids


class PaiementCommande(BaseModel):
    carte_test: str = Field(pattern=MOTIF_CARTE, description=DESCRIPTION_CARTE)


class LigneCommande(BaseModel):
    place_id: UUID
    montant: int = Field(
        description=(
            "Prix de la place en centimes (catégorie de la place au moment de la commande)."
        )
    )


class Commande(BaseModel):
    id: UUID
    seance_id: UUID
    lignes: list[LigneCommande]
    statut: StatutCommande
    montant_total: int = Field(description="Somme des montants des lignes, en centimes.")
    cree_le: datetime
    expire_le: datetime = Field(
        description=(
            "Fin du plus court des verrous de ses places (réservation de 10 minutes par défaut,"
            " configurable ; confirmation de 1 h juste avant Paiements) ; une commande encore"
            " EN_ATTENTE à cette date devient EXPIREE."
        )
    )


class CommandePage(Page[Commande]):
    total: int = Field(description="Nombre total de commandes de l'appelant.")
