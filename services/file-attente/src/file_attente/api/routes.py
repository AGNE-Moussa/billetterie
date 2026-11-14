"""Routes du service : santé, entrée dans la file d'une séance et lecture de sa position.

Rôle `customer` seulement (les revendeurs ne passent pas par la file, risque accepté de
BIL-015). La position est toujours celle de l'appelant du jeton (`sub`), jamais d'un paramètre.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from commun.auth import REPONSE_NON_AUTHENTIFIE, Appelant, exige_role
from commun.erreurs import reponse_probleme
from file_attente.api.dependances import FileDep, ReglesDep, StockageDep
from file_attente.api.schemas import PositionFile, Sante
from file_attente.domaine import file as domaine

routeur_sante = APIRouter(tags=["santé"])
routeur_files = APIRouter(prefix="/api/v1/queues", tags=["file-attente"])

ClientDep = Annotated[Appelant, Depends(exige_role("customer"))]

REPONSES_FILE: dict[int | str, dict[str, Any]] = {
    **REPONSE_NON_AUTHENTIFIE,
    403: reponse_probleme("Rôle manquant, la file est réservée aux clients (ROLE_MANQUANT)."),
    422: reponse_probleme("Identifiant invalide (REQUETE_INVALIDE)."),
    503: reponse_probleme(
        "Redis injoignable ou trop lent, position ni écrite ni lue (FILE_INDISPONIBLE)."
    ),
}


def _position(position: domaine.PositionFile) -> PositionFile:
    return PositionFile(
        seance_id=position.seance_id,
        statut=position.statut,
        position=position.position,
        attente_estimee_secondes=position.attente_estimee_secondes,
        jeton_admission=position.jeton_admission,
        admission_expire_le=position.admission_expire_le,
    )


@routeur_sante.get(
    "/health",
    operation_id="sante",
    response_model=Sante,
    response_description="L'instance et Redis répondent.",
    responses={503: reponse_probleme("Redis ne répond pas.")},
    summary="État de l'instance, appelé par Consul toutes les 10 s",
)
async def sante(file: FileDep) -> Sante:
    await file.verifier()
    return Sante(statut="ok")


@routeur_files.post(
    "/{seance_id}/position",
    operation_id="entrerFile",
    status_code=201,
    response_model=PositionFile,
    response_description="L'appelant entre en fin de file (statut EN_ATTENTE).",
    responses={
        200: {
            "model": PositionFile,
            "description": "L'appelant était déjà dans la file ; position ou admission inchangée.",
        },
        **REPONSES_FILE,
        404: reponse_probleme(
            "Aucune file pour cette séance, séance inconnue ou non sous file (QUEUE_NOT_FOUND)."
        ),
    },
    summary="Entrer dans la file d'attente d'une séance (rôle customer)",
    description=(
        "Place l'appelant du jeton en fin de file de la séance, si elle est sous file. Un"
        " appelant déjà présent garde sa place : la requête répond 200 avec sa position"
        " actuelle (EN_ATTENTE), ou son jeton d'admission s'il est déjà admis et que"
        " l'admission n'a pas expiré ; rafraîchir la page ne fait donc pas perdre sa place."
        " Après expiration de l'admission, l'appelant n'est plus dans la file et rentre en fin"
        " de file."
    ),
)
async def entrer_file(
    seance_id: UUID,
    appelant: ClientDep,
    stockage: StockageDep,
    regles: ReglesDep,
    reponse: Response,
) -> PositionFile:
    position, entre = await domaine.entrer_file(stockage, regles, seance_id, appelant.identifiant)
    if not entre:
        reponse.status_code = 200
    return _position(position)


@routeur_files.get(
    "/{seance_id}/position",
    operation_id="lirePositionFile",
    response_model=PositionFile,
    response_description="Position de l'appelant (EN_ATTENTE) ou son admission (ADMIS).",
    responses={
        **REPONSES_FILE,
        404: reponse_probleme(
            "Aucune file pour cette séance (QUEUE_NOT_FOUND), ou l'appelant n'y est pas, jamais"
            " entré ou admission expirée (QUEUE_POSITION_NOT_FOUND)."
        ),
    },
    summary="Lire ma position dans la file d'attente d'une séance (rôle customer)",
    description=(
        "Position de l'appelant du jeton, relue par la salle d'attente toutes les quelques"
        " secondes. EN_ATTENTE : position et attente estimée. ADMIS : jeton d'admission signé,"
        " à transmettre à creerCommande dans l'en-tête X-Admission-Token jusqu'à"
        " admission_expire_le ; le même jeton est rendu à chaque lecture."
    ),
)
async def lire_position_file(
    seance_id: UUID, appelant: ClientDep, stockage: StockageDep, regles: ReglesDep
) -> PositionFile:
    return _position(await domaine.lire_position(stockage, regles, seance_id, appelant.identifiant))
