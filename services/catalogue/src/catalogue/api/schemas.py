"""Corps des requêtes et des réponses (contrat services/catalogue/openapi.yaml)."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from commun.pagination import Page

# Recherche des événements (paramètres de requête q et ville).
TexteRecherche = Annotated[str, Field(min_length=1, max_length=100)]


class Sante(BaseModel):
    statut: str = Field(examples=["ok"])


class EvenementCreation(BaseModel):
    nom: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=5000)


class Evenement(BaseModel):
    id: UUID
    nom: str
    description: str
    cree_le: datetime


class EvenementPage(Page[Evenement]):
    total: int = Field(description="Nombre total d'événements qui répondent aux filtres.")


class Rang(BaseModel):
    rang: str = Field(min_length=1, max_length=10)
    nombre_places: int = Field(
        ge=1, le=1000, description="Places numérotées de 1 à nombre_places dans le rang."
    )


class CategorieCreation(BaseModel):
    nom: str = Field(min_length=1, max_length=100)
    prix: int = Field(gt=0, description="Prix d'une place de la catégorie, en centimes.")
    rangs: list[Rang] = Field(
        min_length=1,
        max_length=100,
        description=(
            "Rangs de la catégorie ; un rang n'apparaît qu'une fois dans la séance, ni en double"
            " dans la catégorie ni dans une autre catégorie (sinon ROW_ALREADY_ASSIGNED)."
        ),
    )


class Categorie(BaseModel):
    id: UUID
    nom: str
    prix: int = Field(description="Prix d'une place de la catégorie, en centimes.")
    rangs: list[Rang]


class SeanceCreation(BaseModel):
    lieu_id: UUID
    # Date avec fuseau obligatoire (décision Q8 du plan) : sinon 422 REQUETE_INVALIDE.
    debut: AwareDatetime = Field(description="Doit être dans le futur (sinon SHOW_START_IN_PAST).")
    categories: list[CategorieCreation] = Field(
        min_length=1, max_length=20, description="Catégories de places tarifées de la séance."
    )


class Seance(BaseModel):
    id: UUID
    evenement_id: UUID
    lieu_id: UUID
    debut: datetime
    annulee: bool = Field(
        description="Vrai une fois la séance annulée (ticketing.show.cancelled publié)."
    )
    categories: list[Categorie]


class SeancePage(Page[Seance]):
    total: int = Field(description="Nombre total de séances de l'événement.")


class LieuCreation(BaseModel):
    nom: str = Field(min_length=1, max_length=200)
    adresse: str = Field(min_length=1, max_length=300)
    ville: str = Field(min_length=1, max_length=100)


class Lieu(BaseModel):
    id: UUID
    nom: str
    adresse: str
    ville: str
    cree_le: datetime


class LieuPage(Page[Lieu]):
    total: int = Field(description="Nombre total de lieux.")
