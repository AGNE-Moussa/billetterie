"""Corps des requêtes et des réponses (contrat services/paiements/openapi.yaml)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from paiements.domaine.paiements import StatutPaiement

DESCRIPTION_SEANCE = (
    "Séance de la commande ; Paiements consomme ticketing.show.cancelled et rembourse les"
    " paiements ACCEPTE de la séance."
)
DESCRIPTION_MONTANT = "Montant en centimes."


class Sante(BaseModel):
    statut: str = Field(examples=["ok"])


class PaiementCreation(BaseModel):
    commande_id: UUID
    seance_id: UUID = Field(description=DESCRIPTION_SEANCE)
    montant: int = Field(gt=0, description=DESCRIPTION_MONTANT)
    carte_test: str = Field(
        pattern=r"^[0-9]{16}$",
        description=(
            "Numéro de carte du paiement simulé, jamais journalisé. Numéros de test :"
            " 4000000000000002 refusé (PAYMENT_REFUSED), tout autre numéro de 16 chiffres"
            " accepté (par exemple 4242424242424242)."
        ),
    )


class Paiement(BaseModel):
    id: UUID
    commande_id: UUID
    seance_id: UUID = Field(description=DESCRIPTION_SEANCE)
    montant: int = Field(description=DESCRIPTION_MONTANT)
    statut: StatutPaiement
    cree_le: datetime
