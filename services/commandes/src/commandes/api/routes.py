"""Routes du service : santé, création, lecture et paiement des commandes.

`creerCommande` et `payerCommande` exigent le scope orders:write, `listerCommandes` et
`lireCommande` le scope orders:read (client et revendeur). Les règles vivent dans
domaine/commandes.py ; toute lecture filtre par l'appelant du jeton, jamais par un paramètre.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import WithJsonSchema
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from commandes.api.dependances import (
    BilletsDep,
    CatalogueDep,
    DepotDep,
    MaintenantDep,
    PaiementsDep,
    ParametresDep,
    SessionDep,
)
from commandes.api.schemas import (
    Commande,
    CommandeCreation,
    CommandePage,
    LigneCommande,
    PaiementCommande,
    Sante,
)
from commandes.domaine import commandes as domaine
from commandes.infra.base import BaseIndisponible
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
routeur_commandes = APIRouter(prefix="/api/v1/orders", tags=["commandes"])

EcritureDep = Annotated[Appelant, Depends(exige_scopes("orders:write"))]
LectureDep = Annotated[Appelant, Depends(exige_scopes("orders:read"))]
PageDep = Annotated[int, Query(ge=PAGE_MINIMALE)]
TailleDep = Annotated[int, Query(ge=TAILLE_MINIMALE, le=TAILLE_MAXIMALE)]
# Idempotency-Key facultatif de creerCommande (décision Q12) : 100 caractères au plus.
CleIdempotenceDep = Annotated[
    # Schéma explicite : la description reste sur le paramètre, pas dans son schéma (contrat) ;
    # max_length de Header valide toujours la longueur.
    Annotated[
        str | None,
        WithJsonSchema(
            {
                "anyOf": [{"type": "string", "maxLength": 100}, {"type": "null"}],
                "title": "Idempotency-Key",
            }
        ),
    ],
    Header(
        alias="Idempotency-Key",
        max_length=100,
        description=(
            "Facultatif ; une requête terminée, rejouée avec la même clé par le même appelant,"
            " répond 200 avec la commande déjà créée ; rejouée pendant que la première est en"
            " cours, elle répond 409 REQUEST_IN_PROGRESS."
        ),
    ),
]

BASE_INDISPONIBLE = reponse_probleme("Base injoignable (BASE_INDISPONIBLE).")
PAIEMENT_REFUSE = reponse_probleme(
    "Paiement refusé ; la commande expire et ses places sont libérées (PAYMENT_REFUSED)."
)
COMMANDE_INTROUVABLE = reponse_probleme(
    "Aucune commande de l'appelant avec cet identifiant (ORDER_NOT_FOUND)."
)


def _commande(commande: domaine.Commande) -> Commande:
    return Commande(
        id=commande.id,
        seance_id=commande.seance_id,
        lignes=[
            # Montant inconnu (verrou jamais obtenu, commande EXPIREE) : 0 centime.
            LigneCommande(place_id=ligne.place_id, montant=ligne.montant or 0)
            for ligne in commande.lignes
        ],
        statut=commande.statut,
        montant_total=commande.montant_total,
        cree_le=commande.cree_le,
        # Aucun verrou obtenu (commande EXPIREE dès la réservation) : échéance à sa création.
        expire_le=commande.expire_le or commande.cree_le,
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


@routeur_commandes.post(
    "",
    operation_id="creerCommande",
    status_code=201,
    response_model=Commande,
    response_description="Commande créée et payée (statut CONFIRMEE).",
    responses={
        200: {
            "model": Commande,
            "description": (
                "Rejeu d'une requête terminée avec la même Idempotency-Key par le même"
                " appelant ; commande déjà créée."
            ),
        },
        **REPONSES_AUTH,
        402: PAIEMENT_REFUSE,
        404: reponse_probleme(
            "Séance inconnue (SHOW_NOT_FOUND) ou place inconnue dans cette séance (SEAT_NOT_FOUND)."
        ),
        409: reponse_probleme(
            "Place déjà prise (SEAT_ALREADY_TAKEN), nombre maximal de billets par séance"
            " dépassé pour l'appelant (TICKET_LIMIT_EXCEEDED), séance annulée (SHOW_CANCELLED)"
            " ou déjà commencée (SHOW_ALREADY_STARTED), ou requête de même Idempotency-Key"
            " encore en cours (REQUEST_IN_PROGRESS)."
        ),
        422: reponse_probleme("En-tête ou corps invalide (REQUETE_INVALIDE)."),
        503: reponse_probleme(
            "Base injoignable (BASE_INDISPONIBLE), ou Billets, Catalogue ou Paiements"
            " indisponible (SERVICE_INDISPONIBLE). Si Paiements ne répond pas, la commande"
            " reste EN_ATTENTE, ses places verrouillées jusqu'à expire_le ; elle se retrouve"
            " par listerCommandes et se paie par payerCommande."
        ),
    },
    summary=(
        "Commander des places d'une séance et payer (scope orders:write ; client et revendeur)"
    ),
    description=(
        "Crée d'abord la commande EN_ATTENTE, puis verrouille chaque place auprès de Billets en"
        " durée de réservation (prix de chaque ligne lu dans la catégorie de la place) ; un"
        " échec de verrou passe la commande EXPIREE et publie ticketing.order.expired, qui"
        " libère les places déjà verrouillées. Juste avant Paiements, les places sont"
        " reverrouillées en durée de confirmation ; une place perdue donne 409"
        " SEAT_ALREADY_TAKEN, la commande passe EXPIREE, sans aucun débit. Paiement accepté,"
        " la commande est confirmée et ticketing.order.confirmed est publié. La commande"
        " appartient à l'appelant du jeton."
    ),
)
async def creer_commande(
    corps: CommandeCreation,
    appelant: EcritureDep,
    depot: DepotDep,
    catalogue: CatalogueDep,
    billets: BilletsDep,
    paiements: PaiementsDep,
    parametres: ParametresDep,
    maintenant: MaintenantDep,
    reponse: Response,
    cle_idempotence: CleIdempotenceDep = None,
) -> Commande:
    commande, creee = await domaine.creer_commande(
        depot,
        catalogue,
        billets,
        paiements,
        maintenant,
        appelant=appelant,
        seance_id=corps.seance_id,
        place_ids=corps.place_ids,
        carte_test=corps.carte_test,
        cle_idempotence=cle_idempotence,
        limite_billets=parametres.limite_billets_par_seance,
    )
    if not creee:
        # Rejeu d'une requête terminée avec la même Idempotency-Key.
        reponse.status_code = 200
    return _commande(commande)


@routeur_commandes.get(
    "",
    operation_id="listerCommandes",
    response_model=CommandePage,
    response_description="Page des commandes de l'appelant.",
    responses={
        **REPONSES_AUTH,
        422: reponse_probleme("Paramètres de pagination invalides (REQUETE_INVALIDE)."),
        503: BASE_INDISPONIBLE,
    },
    summary="Lister mes commandes, page par page (scope orders:read ; client et revendeur)",
    description=(
        "Filtré par l'appelant du jeton, jamais par un paramètre (règle métier 6). Ordre stable"
        " par date de création décroissante, puis identifiant."
    ),
)
async def lister_commandes(
    appelant: LectureDep,
    depot: DepotDep,
    page: PageDep = PAGE_PAR_DEFAUT,
    size: TailleDep = TAILLE_PAR_DEFAUT,
) -> CommandePage:
    resultat = await domaine.lister_commandes(depot, appelant, page, size)
    return CommandePage(
        elements=[_commande(commande) for commande in resultat.elements],
        page=page,
        size=size,
        total=resultat.total,
    )


@routeur_commandes.get(
    "/{commande_id}",
    operation_id="lireCommande",
    response_model=Commande,
    response_description="Commande de l'appelant.",
    responses={
        **REPONSES_AUTH,
        404: COMMANDE_INTROUVABLE,
        422: reponse_probleme("Identifiant invalide (REQUETE_INVALIDE)."),
        503: BASE_INDISPONIBLE,
    },
    summary="Suivre une de mes commandes (scope orders:read ; client et revendeur)",
)
async def lire_commande(commande_id: UUID, appelant: LectureDep, depot: DepotDep) -> Commande:
    return _commande(await domaine.lire_commande(depot, appelant, commande_id))


@routeur_commandes.post(
    "/{commande_id}/payment",
    operation_id="payerCommande",
    response_model=Commande,
    response_description="Commande payée (statut CONFIRMEE).",
    responses={
        **REPONSES_AUTH,
        402: PAIEMENT_REFUSE,
        404: reponse_probleme(
            "Aucune commande de l'appelant avec cet identifiant (ORDER_NOT_FOUND), ou séance de"
            " la commande inconnue de Catalogue (SHOW_NOT_FOUND)."
        ),
        409: reponse_probleme(
            "La commande n'est pas EN_ATTENTE (ORDER_NOT_PENDING), sa réservation est encore en"
            " cours (REQUEST_IN_PROGRESS), une place est perdue (SEAT_ALREADY_TAKEN ; la"
            " commande passe EXPIREE), ou sa séance est annulée (SHOW_CANCELLED) ou déjà"
            " commencée (SHOW_ALREADY_STARTED ; la commande passe EXPIREE). Un paiement déjà"
            " accepté est signalé à rembourser (ticketing.order.expired, remboursement_du)."
        ),
        422: reponse_probleme("Identifiant ou corps invalide (REQUETE_INVALIDE)."),
        503: reponse_probleme(
            "Base injoignable (BASE_INDISPONIBLE), ou Billets (reverrouillage), Catalogue"
            " (lecture de la séance) ou Paiements indisponible, la commande restant EN_ATTENTE"
            " jusqu'à expire_le (SERVICE_INDISPONIBLE)."
        ),
    },
    summary=(
        "Réessayer le paiement d'une de mes commandes en attente (scope orders:write ; client"
        " et revendeur)"
    ),
    description=(
        "Nouvel essai après un 503 de Paiements, tant que la commande est EN_ATTENTE (avant"
        " expire_le). Juste avant Paiements, les places sont reverrouillées en durée de"
        " confirmation ; une place perdue donne 409 SEAT_ALREADY_TAKEN, la commande passe"
        " EXPIREE, sans aucun débit. Paiement accepté, la commande est confirmée et"
        " ticketing.order.confirmed est publié."
    ),
)
async def payer_commande(
    commande_id: UUID,
    corps: PaiementCommande,
    appelant: EcritureDep,
    depot: DepotDep,
    catalogue: CatalogueDep,
    billets: BilletsDep,
    paiements: PaiementsDep,
    maintenant: MaintenantDep,
) -> Commande:
    commande = await domaine.payer_commande(
        depot,
        catalogue,
        billets,
        paiements,
        maintenant,
        appelant=appelant,
        commande_id=commande_id,
        carte_test=corps.carte_test,
    )
    return _commande(commande)
