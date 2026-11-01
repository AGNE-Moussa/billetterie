"""Événements, lieux et séances du catalogue : règles métier, sans SQLAlchemy."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from commun.erreurs import ErreurMetier

# Publié à chaque séance programmée, dans la transaction de la séance (outbox).
EVENEMENT_SEANCE_PROGRAMMEE = "ticketing.show.scheduled"


@dataclass(frozen=True)
class Evenement:
    id: UUID
    nom: str
    description: str
    cree_le: datetime


@dataclass(frozen=True)
class Lieu:
    id: UUID
    nom: str
    adresse: str
    ville: str
    cree_le: datetime


@dataclass(frozen=True)
class Rang:
    rang: str
    nombre_places: int


@dataclass(frozen=True)
class Categorie:
    id: UUID
    nom: str
    prix: int
    rangs: list[Rang]


@dataclass(frozen=True)
class Seance:
    id: UUID
    evenement_id: UUID
    lieu_id: UUID
    debut: datetime
    annulee: bool
    categories: list[Categorie]


@dataclass(frozen=True)
class NouvelleCategorie:
    nom: str
    prix: int
    rangs: list[Rang]
    # Identifiant imposé (jeu de démonstration, UUID fixes) ; sinon le dépôt en génère un.
    identifiant: UUID | None = None


@dataclass(frozen=True)
class NouvelleSeance:
    lieu_id: UUID
    debut: datetime
    categories: list[NouvelleCategorie]
    # Identifiant imposé (jeu de démonstration, UUID fixes) ; sinon le dépôt en génère un.
    identifiant: UUID | None = None


@dataclass(frozen=True)
class FiltresEvenements:
    """Filtres cumulables de la recherche d'événements ; None : filtre absent."""

    q: str | None = None
    ville: str | None = None
    du: datetime | None = None
    au: datetime | None = None


@dataclass(frozen=True)
class PageResultat[T]:
    elements: list[T]
    total: int


class EvenementIntrouvable(ErreurMetier):
    def __init__(self, evenement_id: UUID) -> None:
        super().__init__(
            "EVENT_NOT_FOUND",
            404,
            f"Aucun événement avec l'identifiant {evenement_id}.",
            titre="Événement introuvable",
        )
        self.evenement_id = evenement_id


class LieuIntrouvable(ErreurMetier):
    def __init__(self, lieu_id: UUID) -> None:
        super().__init__(
            "VENUE_NOT_FOUND",
            404,
            f"Aucun lieu avec l'identifiant {lieu_id}.",
            titre="Lieu introuvable",
        )
        self.lieu_id = lieu_id


class SeanceIntrouvable(ErreurMetier):
    def __init__(self, seance_id: UUID) -> None:
        super().__init__(
            "SHOW_NOT_FOUND",
            404,
            f"Aucune séance avec l'identifiant {seance_id}.",
            titre="Séance introuvable",
        )
        self.seance_id = seance_id


class DebutDansLePasse(ErreurMetier):
    def __init__(self, debut: datetime) -> None:
        super().__init__(
            "SHOW_START_IN_PAST",
            422,
            f"Le début de la séance ({debut.isoformat()}) doit être dans le futur.",
            titre="Début dans le passé",
        )
        self.debut = debut


class RangDejaAttribue(ErreurMetier):
    def __init__(self, rang: str) -> None:
        super().__init__(
            "ROW_ALREADY_ASSIGNED",
            422,
            f"Le rang « {rang} » apparaît plusieurs fois dans la séance.",
            titre="Rang déjà attribué",
        )
        self.rang = rang


class DepotCatalogue(Protocol):
    """Accès aux événements, lieux et séances ; l'implémentation vit dans infra/."""

    async def ajouter_evenement(self, nom: str, description: str) -> Evenement: ...

    async def trouver_evenement(self, evenement_id: UUID) -> Evenement | None: ...

    async def lister_evenements(
        self, filtres: FiltresEvenements, decalage: int, limite: int
    ) -> list[Evenement]:
        """Au plus `limite` événements filtrés après les `decalage` premiers, par date de
        création croissante puis identifiant."""
        ...

    async def compter_evenements(self, filtres: FiltresEvenements) -> int: ...

    async def ajouter_lieu(self, nom: str, adresse: str, ville: str) -> Lieu: ...

    async def trouver_lieu(self, lieu_id: UUID) -> Lieu | None: ...

    async def lister_lieux(self, decalage: int, limite: int) -> list[Lieu]:
        """Par date de création croissante puis identifiant."""
        ...

    async def compter_lieux(self) -> int: ...

    async def ajouter_seance(
        self, evenement: Evenement, lieu: Lieu, nouvelle: NouvelleSeance
    ) -> Seance:
        """Enregistre la séance, ses catégories et ses rangs, et publie
        EVENEMENT_SEANCE_PROGRAMMEE dans la même transaction."""
        ...

    async def trouver_seance(self, seance_id: UUID) -> Seance | None: ...

    async def lister_seances(self, evenement_id: UUID, decalage: int, limite: int) -> list[Seance]:
        """Par début croissant puis identifiant."""
        ...

    async def compter_seances(self, evenement_id: UUID) -> int: ...


def _decalage(page: int, size: int) -> int:
    """Pagination à partir de 1 : nombre d'éléments qui précèdent la page."""
    return (page - 1) * size


async def creer_evenement(depot: DepotCatalogue, nom: str, description: str) -> Evenement:
    return await depot.ajouter_evenement(nom, description)


async def lire_evenement(depot: DepotCatalogue, evenement_id: UUID) -> Evenement:
    evenement = await depot.trouver_evenement(evenement_id)
    if evenement is None:
        raise EvenementIntrouvable(evenement_id)
    return evenement


async def lister_evenements(
    depot: DepotCatalogue, filtres: FiltresEvenements, page: int, size: int
) -> PageResultat[Evenement]:
    """Une page au-delà de la fin est vide ; le total compte tous les événements filtrés."""
    elements = await depot.lister_evenements(filtres, _decalage(page, size), size)
    return PageResultat(elements=elements, total=await depot.compter_evenements(filtres))


async def creer_lieu(depot: DepotCatalogue, nom: str, adresse: str, ville: str) -> Lieu:
    return await depot.ajouter_lieu(nom, adresse, ville)


async def lire_lieu(depot: DepotCatalogue, lieu_id: UUID) -> Lieu:
    lieu = await depot.trouver_lieu(lieu_id)
    if lieu is None:
        raise LieuIntrouvable(lieu_id)
    return lieu


async def lister_lieux(depot: DepotCatalogue, page: int, size: int) -> PageResultat[Lieu]:
    elements = await depot.lister_lieux(_decalage(page, size), size)
    return PageResultat(elements=elements, total=await depot.compter_lieux())


def _rang_en_double(nouvelle: NouvelleSeance) -> str | None:
    """Premier rang présent deux fois dans la séance (comparaison exacte, décision Q12)."""
    vus: set[str] = set()
    for categorie in nouvelle.categories:
        for rang in categorie.rangs:
            if rang.rang in vus:
                return rang.rang
            vus.add(rang.rang)
    return None


async def programmer_seance(
    depot: DepotCatalogue, evenement_id: UUID, nouvelle: NouvelleSeance, maintenant: datetime
) -> Seance:
    """`maintenant` : instant de la requête, injecté pour figer l'horloge dans les tests.

    Erreurs dans l'ordre de la décision Q10 : EVENT_NOT_FOUND, VENUE_NOT_FOUND,
    SHOW_START_IN_PAST, ROW_ALREADY_ASSIGNED.
    """
    evenement = await lire_evenement(depot, evenement_id)
    lieu = await lire_lieu(depot, nouvelle.lieu_id)
    # Strictement dans le futur, sans marge (décision Q9).
    if nouvelle.debut <= maintenant:
        raise DebutDansLePasse(nouvelle.debut)
    rang = _rang_en_double(nouvelle)
    if rang is not None:
        raise RangDejaAttribue(rang)
    return await depot.ajouter_seance(evenement, lieu, nouvelle)


async def lire_seance(depot: DepotCatalogue, evenement_id: UUID, seance_id: UUID) -> Seance:
    await lire_evenement(depot, evenement_id)
    seance = await depot.trouver_seance(seance_id)
    # Une séance d'un autre événement n'existe pas sous celui-ci (décision Q11).
    if seance is None or seance.evenement_id != evenement_id:
        raise SeanceIntrouvable(seance_id)
    return seance


async def lire_seance_par_id(depot: DepotCatalogue, seance_id: UUID) -> Seance:
    seance = await depot.trouver_seance(seance_id)
    if seance is None:
        raise SeanceIntrouvable(seance_id)
    return seance


async def lister_seances(
    depot: DepotCatalogue, evenement_id: UUID, page: int, size: int
) -> PageResultat[Seance]:
    await lire_evenement(depot, evenement_id)
    elements = await depot.lister_seances(evenement_id, _decalage(page, size), size)
    return PageResultat(elements=elements, total=await depot.compter_seances(evenement_id))


def donnees_seance_programmee(seance: Seance, evenement: Evenement, lieu: Lieu) -> dict[str, Any]:
    """`data` de EVENEMENT_SEANCE_PROGRAMMEE (docs/evenements/ticketing.show.scheduled.json)."""
    return {
        "seance_id": str(seance.id),
        "evenement_id": str(evenement.id),
        "evenement_nom": evenement.nom,
        "lieu_id": str(lieu.id),
        "lieu_nom": lieu.nom,
        "ville": lieu.ville,
        "debut": seance.debut.isoformat(),
        "categories": [
            {
                "categorie_id": str(categorie.id),
                "nom": categorie.nom,
                "prix": categorie.prix,
                "rangs": [
                    {"rang": rang.rang, "nombre_places": rang.nombre_places}
                    for rang in categorie.rangs
                ],
            }
            for categorie in seance.categories
        ],
    }
