"""Places des séances et leur verrou : règles métier, sans SQLAlchemy ni Redis.

Une place est disponible si elle ne porte ni verrou (Redis) ni billet (base), quel que soit
le statut du billet (décisions Q7 et Q14 de BIL-006).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from billets.domaine.verrous import MagasinVerrous
from commun.erreurs import ErreurMetier

# Consommé pour créer les places d'une séance (décision Q5).
EVENEMENT_SEANCE_PROGRAMMEE = "ticketing.show.scheduled"
# File durable du consommateur (messages_traites.consommateur, DLQ billets.show-scheduled.dlq).
CONSOMMATEUR_SEANCE_PROGRAMMEE = "billets.show-scheduled"


@dataclass(frozen=True)
class Place:
    id: UUID
    seance_id: UUID
    rang: str
    numero: int
    categorie_id: UUID


@dataclass(frozen=True)
class PlaceDisponibilite:
    """Place et sa disponibilité : ni verrou, ni billet (décision Q7, Q14)."""

    place: Place
    disponible: bool


@dataclass(frozen=True)
class NouvellePlace:
    """Place à créer à la réception de ticketing.show.scheduled."""

    seance_id: UUID
    rang: str
    numero: int
    categorie_id: UUID


@dataclass(frozen=True)
class Verrou:
    place_id: UUID
    seance_id: UUID
    categorie_id: UUID
    commande_id: UUID
    expire_le: datetime


@dataclass(frozen=True)
class DureesVerrou:
    """Durées du verrou, en secondes (décision Q8)."""

    reservation: int
    confirmation: int


@dataclass(frozen=True)
class PageResultat[T]:
    elements: list[T]
    total: int


class PlaceIntrouvable(ErreurMetier):
    def __init__(self, place_id: UUID) -> None:
        super().__init__(
            "SEAT_NOT_FOUND",
            404,
            f"Aucune place avec l'identifiant {place_id} dans cette séance.",
            titre="Place introuvable",
        )
        self.place_id = place_id


class PlaceDejaPrise(ErreurMetier):
    def __init__(self, place_id: UUID) -> None:
        super().__init__(
            "SEAT_ALREADY_TAKEN",
            409,
            f"La place {place_id} est déjà prise.",
            titre="Place déjà prise",
        )
        self.place_id = place_id


class DepotPlaces(Protocol):
    """Accès aux places et aux billets ; lève `BaseIndisponible` si la base ne répond pas."""

    async def lire_place(self, place_id: UUID) -> Place | None:
        """La place, ou None si elle n'existe pas."""
        ...

    async def billet_existe(self, seance_id: UUID, place_id: UUID) -> bool:
        """Vrai si un billet (quel que soit son statut, décision Q14) existe pour la place."""
        ...

    async def places_vendues(self, seance_id: UUID, place_ids: Sequence[UUID]) -> set[UUID]:
        """Parmi `place_ids`, celles qui portent un billet (quel que soit son statut)."""
        ...

    async def lister_places(self, seance_id: UUID, page: int, size: int) -> PageResultat[Place]:
        """Places de la séance par rang (tri binaire), puis numéro, puis identifiant (Q19)."""
        ...

    async def creer_places(self, places: Sequence[NouvellePlace]) -> None:
        """Crée les places ; une place déjà présente (séance, rang, numéro) est ignorée (Q18)."""
        ...


class DonneesSeanceInvalides(ValueError):
    """`data` de ticketing.show.scheduled inexploitable : le message part en file d'erreur
    après trois tentatives (commun.consommateurs)."""


def places_de_la_seance(data: dict[str, Any]) -> list[NouvellePlace]:
    """Places d'une séance programmée (`data` de ticketing.show.scheduled) : numéros de 1 à
    `nombre_places` dans chaque rang, avec la catégorie du rang.

    L'ordre est stable (catégorie, rang, numéro) : deux traitements simultanés de la même séance
    insèrent dans le même ordre, sans interblocage.
    """
    try:
        seance_id = UUID(str(data["seance_id"]))
        places = [
            NouvellePlace(
                seance_id=seance_id,
                rang=str(rang["rang"]),
                numero=numero,
                categorie_id=UUID(str(categorie["categorie_id"])),
            )
            for categorie in data["categories"]
            for rang in categorie["rangs"]
            for numero in range(1, int(rang["nombre_places"]) + 1)
        ]
    except (KeyError, TypeError, ValueError) as erreur:
        raise DonneesSeanceInvalides(f"Séance programmée invalide : {erreur!r}") from erreur
    return sorted(places, key=lambda p: (p.rang.encode(), p.numero))


async def lister_places(
    depot: DepotPlaces, verrous: MagasinVerrous, seance_id: UUID, page: int, size: int
) -> PageResultat[PlaceDisponibilite]:
    """Page de places de la séance avec leur disponibilité.

    La base est lue d'abord (places, billets), Redis ensuite : sans Redis, `VerrouIndisponible`
    (503) plutôt que des places annoncées disponibles à tort (décision Q10).
    """
    resultat = await depot.lister_places(seance_id, page, size)
    if not resultat.elements:
        return PageResultat(elements=[], total=resultat.total)
    identifiants = [place.id for place in resultat.elements]
    vendues = await depot.places_vendues(seance_id, identifiants)
    verrouillees = await verrous.verrouillees(seance_id, identifiants)
    return PageResultat(
        elements=[
            PlaceDisponibilite(
                place=place, disponible=place.id not in vendues and place.id not in verrouillees
            )
            for place in resultat.elements
        ],
        total=resultat.total,
    )


async def verrouiller_place(
    depot: DepotPlaces,
    verrous: MagasinVerrous,
    durees: DureesVerrou,
    maintenant: datetime,
    *,
    place_id: UUID,
    seance_id: UUID,
    commande_id: UUID,
    confirmation: bool,
) -> Verrou:
    """Pose, prolonge ou confirme le verrou de la place pour la commande.

    Ordre des contrôles (décision Q12) : place de la séance (404), billet existant (409), puis
    verrou Redis, seule écriture, atomique (SET NX PX ou script Lua) : aucun « lire puis
    écrire » sur le verrou. Le contrôle du billet avant le verrou est sûr, `uq_billets_place`
    garantit le reste.

    Lève `PlaceIntrouvable` (404), `PlaceDejaPrise` (409) ou `VerrouIndisponible` (503).
    """
    place = await depot.lire_place(place_id)
    if place is None or place.seance_id != seance_id:
        raise PlaceIntrouvable(place_id)
    if await depot.billet_existe(seance_id, place_id):
        raise PlaceDejaPrise(place_id)
    if confirmation:
        restant_ms = await verrous.confirmer(
            seance_id, place_id, commande_id, durees.confirmation * 1000
        )
    else:
        restant_ms = await verrous.poser(
            seance_id, place_id, commande_id, durees.reservation * 1000
        )
    if restant_ms is None:
        raise PlaceDejaPrise(place_id)
    # expire_le = instant de la requête (`maintenant`, fixé avant les lectures en base) + durée
    # restante réellement posée (PTTL rendu par le script). Elle précède donc la fin réelle du
    # verrou de la latence de la requête : légèrement prudente, jamais en retard (Q16).
    return Verrou(
        place_id=place_id,
        seance_id=seance_id,
        categorie_id=place.categorie_id,
        commande_id=commande_id,
        expire_le=maintenant + timedelta(milliseconds=restant_ms),
    )
