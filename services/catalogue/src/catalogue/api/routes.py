"""Routes du service : santé, événements, séances et lieux.

Lectures publiques ; créations réservées au scope events:write. Les règles vivent dans
domaine/catalogue.py : les routes traduisent les corps et les réponses.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.exceptions import RequestValidationError
from pydantic import AwareDatetime
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from catalogue.api.cache_lectures import (
    EN_TETE_CACHE_PERIME,
    FAMILLE_EVENEMENTS,
    FAMILLE_LIEUX,
    famille_seance,
    famille_seances,
)
from catalogue.api.dependances import DepotDep, LecturesDep, MaintenantDep, SessionDep
from catalogue.api.schemas import (
    Categorie,
    Evenement,
    EvenementCreation,
    EvenementPage,
    Lieu,
    LieuCreation,
    LieuPage,
    Rang,
    Sante,
    Seance,
    SeanceCreation,
    SeancePage,
    TexteRecherche,
)
from catalogue.domaine import catalogue as domaine
from catalogue.infra.base import BaseIndisponible
from commun.auth import REPONSES_AUTH, Appelant, exige_role, exige_scopes
from commun.erreurs import reponse_probleme
from commun.pagination import (
    PAGE_MINIMALE,
    PAGE_PAR_DEFAUT,
    TAILLE_MAXIMALE,
    TAILLE_MINIMALE,
    TAILLE_PAR_DEFAUT,
)

routeur_sante = APIRouter(tags=["santé"])
routeur_evenements = APIRouter(prefix="/api/v1/events", tags=["événements"])
routeur_seances = APIRouter(tags=["séances"])
routeur_lieux = APIRouter(prefix="/api/v1/venues", tags=["lieux"])

# Écritures réservées au scope events:write seul (décision Q5 du plan BIL-004).
EcrivainDep = Annotated[Appelant, Depends(exige_scopes("events:write"))]
_exige_admin = exige_role("admin")
_exige_ecriture = exige_scopes("events:write")


async def _administrateur(appelant: Annotated[Appelant, Depends(_exige_admin)]) -> Appelant:
    """Rôle `admin` contrôlé avant le scope `events:write` (contrainte de BIL-011, H2) : un
    client ou un revendeur reçoit ROLE_MANQUANT, un admin sans le scope SCOPE_MANQUANT."""
    return await _exige_ecriture(appelant)


AdministrateurDep = Annotated[Appelant, Depends(_administrateur)]
PageDep = Annotated[int, Query(ge=PAGE_MINIMALE)]
TailleDep = Annotated[int, Query(ge=TAILLE_MINIMALE, le=TAILLE_MAXIMALE)]

BASE_INDISPONIBLE_ECRITURE = reponse_probleme("Base injoignable (BASE_INDISPONIBLE).")
BASE_INDISPONIBLE_LISTE = reponse_probleme(
    "Base injoignable et données absentes du cache (BASE_INDISPONIBLE)."
)
BASE_INDISPONIBLE_LECTURE = reponse_probleme(
    "Base injoignable et donnée absente du cache (BASE_INDISPONIBLE)."
)
IDENTIFIANT_INVALIDE = reponse_probleme("Identifiant invalide (REQUETE_INVALIDE).")

# Lectures servies par le cache Redis (BIL-005) : la route renvoie le corps JSON déjà
# sérialisé (`LecturesEnCache.servir`), identique octet pour octet entre la base et le cache ;
# `response_model` reste déclaré pour le contrat. En-tête de la copie de secours : D1 à D4.
REPONSE_LECTURE: dict[str, Any] = {
    "headers": {
        EN_TETE_CACHE_PERIME: {
            "description": (
                "Présent, valeur true, seulement quand la réponse vient du cache Redis parce que"
                " la base ne répond pas (mode dégradé) ; absent sinon."
            ),
            "schema": {"type": "string", "enum": ["true"]},
        }
    }
}


def _evenement(evenement: domaine.Evenement) -> Evenement:
    return Evenement(
        id=evenement.id,
        nom=evenement.nom,
        description=evenement.description,
        cree_le=evenement.cree_le,
    )


def _lieu(lieu: domaine.Lieu) -> Lieu:
    return Lieu(
        id=lieu.id, nom=lieu.nom, adresse=lieu.adresse, ville=lieu.ville, cree_le=lieu.cree_le
    )


def _seance(seance: domaine.Seance) -> Seance:
    return Seance(
        id=seance.id,
        evenement_id=seance.evenement_id,
        lieu_id=seance.lieu_id,
        debut=seance.debut,
        annulee=seance.annulee,
        categories=[
            Categorie(
                id=categorie.id,
                nom=categorie.nom,
                prix=categorie.prix,
                rangs=[
                    Rang(rang=rang.rang, nombre_places=rang.nombre_places)
                    for rang in categorie.rangs
                ],
            )
            for categorie in seance.categories
        ],
    )


@routeur_sante.get(
    "/health",
    operation_id="sante",
    response_model=Sante,
    response_description="L'instance et sa base répondent.",
    responses={503: reponse_probleme("La base de données ne répond pas.")},
    summary="État de l'instance, appelé par Consul toutes les 10 s",
)
async def sante(session: SessionDep) -> Sante:
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as erreur:
        raise BaseIndisponible() from erreur
    return Sante(statut="ok")


@routeur_evenements.get(
    "",
    operation_id="listerEvenements",
    response_model=EvenementPage,
    response_description="Page d'événements (depuis le cache Redis si la base ne répond pas).",
    responses={
        422: reponse_probleme(
            "Filtres ou pagination invalides, ou du postérieur à au (REQUETE_INVALIDE)."
        ),
        200: REPONSE_LECTURE,
        503: BASE_INDISPONIBLE_LISTE,
    },
    summary="Rechercher les événements, page par page (route publique)",
    description=(
        "Filtres facultatifs et cumulables. q cherche dans le nom et la description ; ville, du"
        " et au retiennent les événements qui ont au moins une séance dans cette ville et dans"
        " cet intervalle (bornes incluses). Ordre stable par date de création croissante, puis"
        " identifiant."
    ),
)
async def lister_evenements(
    depot: DepotDep,
    lectures: LecturesDep,
    q: Annotated[TexteRecherche | None, Query()] = None,
    ville: Annotated[TexteRecherche | None, Query()] = None,
    # Dates avec fuseau obligatoire (décision Q8 du plan) : sinon 422 REQUETE_INVALIDE.
    du: Annotated[AwareDatetime | None, Query()] = None,
    au: Annotated[AwareDatetime | None, Query()] = None,
    page: PageDep = PAGE_PAR_DEFAUT,
    size: TailleDep = TAILLE_PAR_DEFAUT,
) -> Response:
    if du is not None and au is not None and du > au:
        # Décision S1 : même réponse qu'une erreur de validation, qui nomme le paramètre fautif.
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("query", "du"),
                    "msg": "du doit être antérieur ou égal à au",
                    "input": du.isoformat(),
                }
            ]
        )
    filtres = domaine.FiltresEvenements(q=q, ville=ville, du=du, au=au)

    async def lire() -> EvenementPage:
        resultat = await domaine.lister_evenements(depot, filtres, page, size)
        return EvenementPage(
            elements=[_evenement(evenement) for evenement in resultat.elements],
            page=page,
            size=size,
            total=resultat.total,
        )

    return await lectures.servir(
        "listerEvenements",
        {"q": q, "ville": ville, "du": du, "au": au, "page": page, "size": size},
        lire,
        famille=FAMILLE_EVENEMENTS,
    )


@routeur_evenements.post(
    "",
    operation_id="creerEvenement",
    status_code=201,
    response_model=Evenement,
    response_description="Événement créé.",
    responses={
        **REPONSES_AUTH,
        422: reponse_probleme("Corps invalide (REQUETE_INVALIDE)."),
        503: BASE_INDISPONIBLE_ECRITURE,
    },
    summary="Créer un événement (scope events:write ; admin)",
)
async def creer_evenement(
    corps: EvenementCreation, depot: DepotDep, lectures: LecturesDep, _appelant: EcrivainDep
) -> Evenement:
    cree = await domaine.creer_evenement(depot, corps.nom, corps.description)
    # Après le commit seulement (Q15) : une erreur plus haut n'invalide rien.
    await lectures.invalider(FAMILLE_EVENEMENTS)
    return _evenement(cree)


@routeur_evenements.get(
    "/{evenement_id}",
    operation_id="lireEvenement",
    response_model=Evenement,
    response_description="Détail de l'événement (depuis le cache Redis si la base ne répond pas).",
    responses={
        404: reponse_probleme("Aucun événement avec cet identifiant (EVENT_NOT_FOUND)."),
        422: IDENTIFIANT_INVALIDE,
        200: REPONSE_LECTURE,
        503: BASE_INDISPONIBLE_LECTURE,
    },
    summary="Lire le détail d'un événement (route publique)",
)
async def lire_evenement(evenement_id: UUID, depot: DepotDep, lectures: LecturesDep) -> Response:
    async def lire() -> Evenement:
        return _evenement(await domaine.lire_evenement(depot, evenement_id))

    return await lectures.servir("lireEvenement", {"evenement_id": evenement_id}, lire)


@routeur_seances.get(
    "/api/v1/events/{evenement_id}/shows",
    operation_id="listerSeances",
    response_model=SeancePage,
    response_description="Page de séances (depuis le cache Redis si la base ne répond pas).",
    responses={
        404: reponse_probleme("Aucun événement avec cet identifiant (EVENT_NOT_FOUND)."),
        422: reponse_probleme(
            "Identifiant ou paramètres de pagination invalides (REQUETE_INVALIDE)."
        ),
        200: REPONSE_LECTURE,
        503: BASE_INDISPONIBLE_LISTE,
    },
    summary=(
        "Lister les séances d'un événement avec leurs catégories, page par page (route publique)"
    ),
    description="Ordre stable par début croissant, puis identifiant.",
)
async def lister_seances(
    evenement_id: UUID,
    depot: DepotDep,
    lectures: LecturesDep,
    page: PageDep = PAGE_PAR_DEFAUT,
    size: TailleDep = TAILLE_PAR_DEFAUT,
) -> Response:
    async def lire() -> SeancePage:
        resultat = await domaine.lister_seances(depot, evenement_id, page, size)
        return SeancePage(
            elements=[_seance(seance) for seance in resultat.elements],
            page=page,
            size=size,
            total=resultat.total,
        )

    return await lectures.servir(
        "listerSeances",
        {"evenement_id": evenement_id, "page": page, "size": size},
        lire,
        famille=famille_seances(evenement_id),
    )


@routeur_seances.post(
    "/api/v1/events/{evenement_id}/shows",
    operation_id="creerSeance",
    status_code=201,
    response_model=Seance,
    response_description="Séance créée.",
    responses={
        **REPONSES_AUTH,
        404: reponse_probleme("Événement ou lieu inconnu (EVENT_NOT_FOUND, VENUE_NOT_FOUND)."),
        422: reponse_probleme(
            "Identifiant ou corps invalide (REQUETE_INVALIDE), début dans le passé"
            " (SHOW_START_IN_PAST) ou même rang deux fois dans la séance, dans une même catégorie"
            " ou dans deux (ROW_ALREADY_ASSIGNED)."
        ),
        503: BASE_INDISPONIBLE_ECRITURE,
    },
    summary=(
        "Programmer une séance dans un lieu, avec ses catégories de places (scope events:write ;"
        " admin)"
    ),
    description=(
        "Publie ticketing.show.scheduled, qui porte aussi le nom de l'événement, le nom et la"
        " ville du lieu."
    ),
)
async def creer_seance(
    evenement_id: UUID,
    corps: SeanceCreation,
    depot: DepotDep,
    maintenant: MaintenantDep,
    lectures: LecturesDep,
    _appelant: EcrivainDep,
) -> Seance:
    nouvelle = domaine.NouvelleSeance(
        lieu_id=corps.lieu_id,
        debut=corps.debut,
        categories=[
            domaine.NouvelleCategorie(
                nom=categorie.nom,
                prix=categorie.prix,
                rangs=[
                    domaine.Rang(rang=rang.rang, nombre_places=rang.nombre_places)
                    for rang in categorie.rangs
                ],
            )
            for categorie in corps.categories
        ],
    )
    programmee = await domaine.programmer_seance(depot, evenement_id, nouvelle, maintenant)
    # Après le commit seulement (Q15). Les listes d'événements dépendent des séances (filtres
    # ville, du, au) : elles sont invalidées aussi (matrice Q13).
    await lectures.invalider(famille_seances(evenement_id), FAMILLE_EVENEMENTS)
    return _seance(programmee)


@routeur_seances.get(
    "/api/v1/events/{evenement_id}/shows/{seance_id}",
    operation_id="lireSeance",
    response_model=Seance,
    response_description="Séance (depuis le cache Redis si la base ne répond pas).",
    responses={
        404: reponse_probleme("Événement ou séance inconnu (EVENT_NOT_FOUND, SHOW_NOT_FOUND)."),
        422: IDENTIFIANT_INVALIDE,
        200: REPONSE_LECTURE,
        503: BASE_INDISPONIBLE_LECTURE,
    },
    summary="Lire une séance avec ses catégories de places (route publique)",
)
async def lire_seance(
    evenement_id: UUID, seance_id: UUID, depot: DepotDep, lectures: LecturesDep
) -> Response:
    async def lire() -> Seance:
        return _seance(await domaine.lire_seance(depot, evenement_id, seance_id))

    return await lectures.servir(
        "lireSeance",
        {"evenement_id": evenement_id, "seance_id": seance_id},
        lire,
        famille=famille_seance(seance_id),
    )


@routeur_seances.post(
    "/api/v1/events/{evenement_id}/shows/{seance_id}/cancellation",
    operation_id="annulerSeance",
    response_model=Seance,
    response_description="Séance annulée.",
    responses={
        **REPONSES_AUTH,
        404: reponse_probleme("Événement ou séance inconnu (EVENT_NOT_FOUND, SHOW_NOT_FOUND)."),
        409: reponse_probleme(
            "La séance est déjà annulée (SHOW_ALREADY_CANCELLED) ou déjà commencée"
            " (SHOW_ALREADY_STARTED)."
        ),
        422: IDENTIFIANT_INVALIDE,
        503: BASE_INDISPONIBLE_ECRITURE,
    },
    summary="Annuler une séance (scope events:write ; admin)",
    description=(
        "Publie ticketing.show.cancelled ; toutes les commandes de la séance sont remboursées"
        " automatiquement (règle métier 5) et ses billets annulés."
    ),
)
async def annuler_seance(
    evenement_id: UUID,
    seance_id: UUID,
    depot: DepotDep,
    maintenant: MaintenantDep,
    lectures: LecturesDep,
    _appelant: AdministrateurDep,
) -> Seance:
    annulee = await domaine.annuler_seance(depot, evenement_id, seance_id, maintenant)
    # Après le commit seulement (H3) : nouvelle génération des deux lectures de détail de la
    # séance et des listes de séances de l'événement. Une lecture commencée avant le commit
    # écrit sous l'ancienne génération, que plus aucune lecture ne consulte.
    await lectures.invalider(famille_seance(seance_id), famille_seances(evenement_id))
    return _seance(annulee)


@routeur_seances.get(
    "/api/v1/shows/{seance_id}",
    operation_id="lireSeanceParId",
    response_model=Seance,
    response_description="Séance (depuis le cache Redis si la base ne répond pas).",
    responses={
        404: reponse_probleme("Aucune séance avec cet identifiant (SHOW_NOT_FOUND)."),
        422: IDENTIFIANT_INVALIDE,
        200: REPONSE_LECTURE,
        503: BASE_INDISPONIBLE_LECTURE,
    },
    summary=(
        "Lire une séance par son seul identifiant, avec ses catégories de places (route publique)"
    ),
    description="Utilisée notamment par Commandes, qui ne connaît que la séance de la commande.",
)
async def lire_seance_par_id(seance_id: UUID, depot: DepotDep, lectures: LecturesDep) -> Response:
    async def lire() -> Seance:
        return _seance(await domaine.lire_seance_par_id(depot, seance_id))

    return await lectures.servir(
        "lireSeanceParId", {"seance_id": seance_id}, lire, famille=famille_seance(seance_id)
    )


@routeur_lieux.get(
    "",
    operation_id="listerLieux",
    response_model=LieuPage,
    response_description="Page de lieux (depuis le cache Redis si la base ne répond pas).",
    responses={
        422: reponse_probleme("Paramètres de pagination invalides (REQUETE_INVALIDE)."),
        200: REPONSE_LECTURE,
        503: BASE_INDISPONIBLE_LISTE,
    },
    summary="Lister les lieux, page par page (route publique)",
    description="Ordre stable par date de création croissante, puis identifiant.",
)
async def lister_lieux(
    depot: DepotDep,
    lectures: LecturesDep,
    page: PageDep = PAGE_PAR_DEFAUT,
    size: TailleDep = TAILLE_PAR_DEFAUT,
) -> Response:
    async def lire() -> LieuPage:
        resultat = await domaine.lister_lieux(depot, page, size)
        return LieuPage(
            elements=[_lieu(lieu) for lieu in resultat.elements],
            page=page,
            size=size,
            total=resultat.total,
        )

    return await lectures.servir(
        "listerLieux", {"page": page, "size": size}, lire, famille=FAMILLE_LIEUX
    )


@routeur_lieux.post(
    "",
    operation_id="creerLieu",
    status_code=201,
    response_model=Lieu,
    response_description="Lieu créé.",
    responses={
        **REPONSES_AUTH,
        422: reponse_probleme("Corps invalide (REQUETE_INVALIDE)."),
        503: BASE_INDISPONIBLE_ECRITURE,
    },
    summary="Créer un lieu (scope events:write ; admin)",
)
async def creer_lieu(
    corps: LieuCreation, depot: DepotDep, lectures: LecturesDep, _appelant: EcrivainDep
) -> Lieu:
    cree = await domaine.creer_lieu(depot, corps.nom, corps.adresse, corps.ville)
    # Après le commit seulement (Q15).
    await lectures.invalider(FAMILLE_LIEUX)
    return _lieu(cree)


@routeur_lieux.get(
    "/{lieu_id}",
    operation_id="lireLieu",
    response_model=Lieu,
    response_description="Lieu (depuis le cache Redis si la base ne répond pas).",
    responses={
        404: reponse_probleme("Aucun lieu avec cet identifiant (VENUE_NOT_FOUND)."),
        422: IDENTIFIANT_INVALIDE,
        200: REPONSE_LECTURE,
        503: BASE_INDISPONIBLE_LECTURE,
    },
    summary="Lire un lieu (route publique)",
)
async def lire_lieu(lieu_id: UUID, depot: DepotDep, lectures: LecturesDep) -> Response:
    async def lire() -> Lieu:
        return _lieu(await domaine.lire_lieu(depot, lieu_id))

    return await lectures.servir("lireLieu", {"lieu_id": lieu_id}, lire)
