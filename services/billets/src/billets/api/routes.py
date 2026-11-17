"""Routes du service : santé, disponibilité des places, verrou d'une place, billets de
l'appelant.

`listerPlaces` est publique ; `verrouillerPlace` exige le scope seats:lock (client services,
décisions Q3 et Q17 de BIL-006). Les règles vivent dans domaine/places.py. `listerBillets` et
`lireBillet` exigent le scope tickets:read (client et revendeur, BIL-021) et filtrent toujours
par l'appelant du jeton, jamais par un paramètre (domaine/consultation.py).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from billets.api.dependances import (
    DepotBilletsDep,
    DepotDep,
    DureesDep,
    MaintenantDep,
    SessionDep,
    VerrousDep,
)
from billets.api.schemas import (
    Billet,
    BilletPage,
    Place,
    PlacePage,
    Sante,
    Verrou,
    VerrouCreation,
)
from billets.domaine import consultation
from billets.domaine import places as domaine
from billets.infra.base import BaseIndisponible
from commun.auth import REPONSES_AUTH, Appelant, exige_scopes
from commun.erreurs import reponse_probleme
from commun.pagination import (
    PAGE_MINIMALE,
    PAGE_PAR_DEFAUT,
    TAILLE_MAXIMALE,
    TAILLE_MINIMALE,
    TAILLE_PAR_DEFAUT,
)

routeur_sante = APIRouter(tags=["santé"])
routeur_places = APIRouter(prefix="/api/v1/seats", tags=["places"])
routeur_billets = APIRouter(prefix="/api/v1/tickets", tags=["billets"])

# Verrou réservé au scope seats:lock seul (décision Q17 du plan BIL-006).
ServiceDep = Annotated[Appelant, Depends(exige_scopes("seats:lock"))]
LectureBilletsDep = Annotated[Appelant, Depends(exige_scopes("tickets:read"))]
PageDep = Annotated[int, Query(ge=PAGE_MINIMALE)]
TailleDep = Annotated[int, Query(ge=TAILLE_MINIMALE, le=TAILLE_MAXIMALE)]

# Une description commune aux deux routes (décisions du plan, Q9 à Q11).
INDISPONIBLE = reponse_probleme(
    "Base injoignable (BASE_INDISPONIBLE), ou Redis injoignable ou trop lent, verrou ni posé ni"
    " lu (VERROU_INDISPONIBLE)."
)
# Routes des billets : la base seule, jamais Redis.
BASE_INDISPONIBLE = reponse_probleme("Base injoignable (BASE_INDISPONIBLE).")


def _billet(billet: consultation.BilletLu) -> Billet:
    return Billet(
        id=billet.id,
        commande_id=billet.commande_id,
        seance_id=billet.seance_id,
        place_id=billet.place_id,
        rang=billet.rang,
        numero=billet.numero,
        statut=billet.statut,
        qr_code=billet.qr_code,
        emis_le=billet.emis_le,
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
    # Ne dépend que de la base, jamais de Redis (décision Q21).
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as erreur:
        raise BaseIndisponible() from erreur
    return Sante(statut="ok")


@routeur_places.get(
    "",
    operation_id="listerPlaces",
    response_model=PlacePage,
    response_description="Page de places de la séance, avec leur disponibilité.",
    responses={
        422: reponse_probleme(
            "Séance absente ou invalide, ou pagination invalide (REQUETE_INVALIDE)."
        ),
        503: INDISPONIBLE,
    },
    summary="Disponibilité des places d'une séance, page par page (route publique)",
    description=(
        "Ordre stable par rang, puis numéro. Une séance inconnue ou sans place répond 200 avec"
        " elements vide."
    ),
)
async def lister_places(
    depot: DepotDep,
    verrous: VerrousDep,
    seance_id: Annotated[UUID, Query()],
    page: PageDep = PAGE_PAR_DEFAUT,
    size: TailleDep = TAILLE_PAR_DEFAUT,
) -> PlacePage:
    resultat = await domaine.lister_places(depot, verrous, seance_id, page, size)
    return PlacePage(
        elements=[
            Place(
                id=element.place.id,
                seance_id=element.place.seance_id,
                rang=element.place.rang,
                numero=element.place.numero,
                categorie_id=element.place.categorie_id,
                disponible=element.disponible,
            )
            for element in resultat.elements
        ],
        page=page,
        size=size,
        total=resultat.total,
    )


@routeur_places.put(
    "/{place_id}/lock",
    operation_id="verrouillerPlace",
    response_model=Verrou,
    response_description="Place verrouillée au profit de la commande (verrou posé ou prolongé).",
    responses={
        **REPONSES_AUTH,
        404: reponse_probleme(
            "Aucune place avec cet identifiant dans cette séance (SEAT_NOT_FOUND)."
        ),
        409: reponse_probleme(
            "Place verrouillée par une autre commande ou vendue, ou confirmation demandée sans"
            " détenir le verrou (SEAT_ALREADY_TAKEN)."
        ),
        422: reponse_probleme("Identifiant ou corps invalide (REQUETE_INVALIDE)."),
        503: INDISPONIBLE,
    },
    summary=(
        "Verrouiller une place pour une commande (scope seats:lock ; client services seulement)"
    ),
    description=(
        "Verrou Redis SET NX PX dont le propriétaire (valeur de la clé) est la commande (règles"
        " métier 1 et 2). confirmation à false : durée de réservation (10 min par défaut,"
        " configurable) ; idempotent, un nouvel appel pour la même commande répond 200 et"
        " prolonge le verrou. confirmation à true : durée de confirmation (1 h par défaut,"
        " configurable), accordée seulement à la commande qui détient déjà le verrou, sinon 409"
        " SEAT_ALREADY_TAKEN ; Commandes l'appelle juste avant Paiements. Billets supprime le"
        " verrou une fois le billet émis ; ticketing.order.expired ne libère la place que si la"
        " valeur de la clé est cette commande."
    ),
)
async def verrouiller_place(
    place_id: UUID,
    corps: VerrouCreation,
    _appelant: ServiceDep,
    depot: DepotDep,
    verrous: VerrousDep,
    durees: DureesDep,
    maintenant: MaintenantDep,
) -> Verrou:
    verrou = await domaine.verrouiller_place(
        depot,
        verrous,
        durees,
        maintenant,
        place_id=place_id,
        seance_id=corps.seance_id,
        commande_id=corps.commande_id,
        confirmation=corps.confirmation,
    )
    return Verrou(
        place_id=verrou.place_id,
        seance_id=verrou.seance_id,
        categorie_id=verrou.categorie_id,
        commande_id=verrou.commande_id,
        expire_le=verrou.expire_le,
    )


@routeur_billets.get(
    "",
    operation_id="listerBillets",
    response_model=BilletPage,
    response_description="Page des billets de l'appelant.",
    responses={
        **REPONSES_AUTH,
        422: reponse_probleme(
            "Identifiant de commande ou paramètres de pagination invalides (REQUETE_INVALIDE)."
        ),
        503: BASE_INDISPONIBLE,
    },
    summary="Lister mes billets, page par page (scope tickets:read ; client et revendeur)",
    description=(
        "Filtré par l'appelant du jeton, jamais par un paramètre ; commande_id, s'il est"
        " fourni, restreint en plus aux billets de cette commande (une commande inconnue ou"
        " d'un autre appelant répond 200 avec elements vide). Ordre stable par date d'émission"
        " décroissante, puis identifiant."
    ),
)
async def lister_billets(
    appelant: LectureBilletsDep,
    depot: DepotBilletsDep,
    commande_id: Annotated[UUID | None, Query()] = None,
    page: PageDep = PAGE_PAR_DEFAUT,
    size: TailleDep = TAILLE_PAR_DEFAUT,
) -> BilletPage:
    resultat = await consultation.lister_billets(depot, appelant, commande_id, page, size)
    return BilletPage(
        elements=[_billet(billet) for billet in resultat.elements],
        page=page,
        size=size,
        total=resultat.total,
    )


@routeur_billets.get(
    "/{billet_id}",
    operation_id="lireBillet",
    response_model=Billet,
    response_description="Billet de l'appelant.",
    responses={
        **REPONSES_AUTH,
        404: reponse_probleme(
            "Aucun billet de l'appelant avec cet identifiant (TICKET_NOT_FOUND)."
        ),
        422: reponse_probleme("Identifiant invalide (REQUETE_INVALIDE)."),
        503: BASE_INDISPONIBLE,
    },
    summary=("Lire un de mes billets, avec son QR code (scope tickets:read ; client et revendeur)"),
    description=(
        "Un billet d'un autre appelant répond 404 TICKET_NOT_FOUND, comme un billet"
        " inexistant, jamais 403."
    ),
)
async def lire_billet(
    billet_id: UUID, appelant: LectureBilletsDep, depot: DepotBilletsDep
) -> Billet:
    return _billet(await consultation.lire_billet(depot, appelant, billet_id))
