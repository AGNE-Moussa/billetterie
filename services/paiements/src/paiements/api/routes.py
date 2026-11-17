"""Routes du service : santé, paiement simulé d'une commande et sa lecture.

`creerPaiement` et `lirePaiement` exigent le scope payments:write (client services seulement,
décision Q4 et review, point 3, de BIL-008). Les règles vivent dans domaine/paiements.py.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import WithJsonSchema
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from commun.auth import REPONSES_AUTH, Appelant, exige_scopes
from commun.erreurs import reponse_probleme
from paiements.api.dependances import DepotDep, MaintenantDep, SessionDep
from paiements.api.schemas import Paiement, PaiementCreation, Sante
from paiements.domaine import paiements as domaine
from paiements.infra.base import BaseIndisponible

routeur_sante = APIRouter(tags=["santé"])
routeur_paiements = APIRouter(prefix="/api/v1/payments", tags=["paiements"])

ServiceDep = Annotated[Appelant, Depends(exige_scopes("payments:write"))]
# Idempotency-Key obligatoire, égal à commande_id (décisions Q6 et Q12).
CleIdempotenceDep = Annotated[
    # Schéma explicite : la description reste sur le paramètre, pas dans son schéma (contrat).
    Annotated[
        UUID,
        WithJsonSchema({"type": "string", "format": "uuid", "title": "Idempotency-Key"}),
    ],
    Header(
        alias="Idempotency-Key",
        description="Identifiant de la commande payée (même valeur que commande_id).",
    ),
]


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


@routeur_paiements.post(
    "",
    operation_id="creerPaiement",
    status_code=201,
    response_model=Paiement,
    response_description="Paiement accepté (statut ACCEPTE).",
    responses={
        **REPONSES_AUTH,
        402: reponse_probleme(
            "Paiement refusé, enregistré avec le statut REFUSE (PAYMENT_REFUSED)."
        ),
        409: reponse_probleme(
            "Un paiement différent existe déjà pour cette commande (PAYMENT_ALREADY_EXISTS),"
            " ou la séance est annulée d'après la projection des séances annulées"
            " (SHOW_CANCELLED)."
        ),
        422: reponse_probleme(
            "En-tête ou corps invalide, ou Idempotency-Key différent de commande_id"
            " (REQUETE_INVALIDE)."
        ),
        503: reponse_probleme("Base injoignable (BASE_INDISPONIBLE)."),
    },
    summary=("Payer une commande en mode test (scope payments:write ; client services seulement)"),
    description=(
        "Paiement simulé, aucune donnée de carte réelle ; le numéro de carte n'est ni"
        " journalisé ni conservé. Un seul paiement par commande. Idempotent par"
        " Idempotency-Key (égal à commande_id) ; une requête rejouée à l'identique renvoie le"
        " résultat enregistré (201 ou 402), sans nouveau paiement."
    ),
)
async def creer_paiement(
    corps: PaiementCreation,
    cle_idempotence: CleIdempotenceDep,
    _appelant: ServiceDep,
    depot: DepotDep,
    maintenant: MaintenantDep,
) -> Paiement:
    paiement = await domaine.payer(
        depot,
        maintenant,
        cle_idempotence=cle_idempotence,
        commande_id=corps.commande_id,
        seance_id=corps.seance_id,
        montant=corps.montant,
        carte_test=corps.carte_test,
    )
    return _paiement(paiement)


@routeur_paiements.get(
    "/{commande_id}",
    operation_id="lirePaiement",
    response_model=Paiement,
    response_description="Paiement de la commande.",
    responses={
        **REPONSES_AUTH,
        404: reponse_probleme("Aucun paiement pour cette commande (PAYMENT_NOT_FOUND)."),
        422: reponse_probleme("Paramètre de chemin invalide (REQUETE_INVALIDE)."),
        503: reponse_probleme("Base injoignable (BASE_INDISPONIBLE)."),
    },
    summary="Lire le paiement d'une commande (scope payments:write ; client services seulement)",
    description=(
        "Lecture sans effet, utilisée par Commandes avant d'expirer une commande déjà envoyée"
        " à Paiements, pour savoir si un remboursement est dû ; ne crée jamais de paiement."
    ),
)
async def lire_paiement(commande_id: UUID, _appelant: ServiceDep, depot: DepotDep) -> Paiement:
    return _paiement(await domaine.lire_paiement(depot, commande_id))


def _paiement(paiement: domaine.Paiement) -> Paiement:
    return Paiement(
        id=paiement.id,
        commande_id=paiement.commande_id,
        seance_id=paiement.seance_id,
        montant=paiement.montant,
        statut=paiement.statut,
        cree_le=paiement.cree_le,
    )
