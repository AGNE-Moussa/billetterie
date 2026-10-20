"""Routes du service : santé et echos."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from commun.auth import REPONSE_NON_AUTHENTIFIE, REPONSES_AUTH, Appelant, AppelantDep, exige_scopes
from commun.erreurs import ErreurMetier, reponse_probleme
from echo.api.dependances import DepotDep, ParametresDep, SessionDep
from echo.api.schemas import EchoCreation, EchoReponse, Message, Sante
from echo.domaine.echos import Echo, enregistrer_echo, lire_echo

routeur_sante = APIRouter(tags=["santé"])
routeur_echos = APIRouter(prefix="/api/v1/echos", tags=["echos"])


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
        raise ErreurMetier(
            "BASE_INDISPONIBLE",
            503,
            "La base de données ne répond pas.",
            titre="Service indisponible",
        ) from erreur
    return Sante(statut="ok")


def _reponse(echo: Echo, parametres: ParametresDep) -> EchoReponse:
    return EchoReponse(message=echo.message, instance=parametres.instance, cree_le=echo.cree_le)


@routeur_echos.post(
    "",
    operation_id="creerEcho",
    status_code=201,
    response_model=EchoReponse,
    response_description="Message enregistré.",
    responses={
        **REPONSES_AUTH,
        409: reponse_probleme("Le message est déjà enregistré (ECHO_EXISTANT)."),
        422: reponse_probleme("Corps invalide (REQUETE_INVALIDE)."),
    },
    summary="Enregistrer un message (scope echos:write)",
)
async def creer_echo(
    corps: EchoCreation,
    depot: DepotDep,
    parametres: ParametresDep,
    _appelant: Annotated[Appelant, Depends(exige_scopes("echos:write"))],
) -> EchoReponse:
    return _reponse(await enregistrer_echo(depot, corps.message), parametres)


@routeur_echos.get(
    "/{message}",
    operation_id="lireEcho",
    response_model=EchoReponse,
    response_description="Message enregistré, avec l'instance qui a répondu.",
    responses={
        **REPONSE_NON_AUTHENTIFIE,
        404: reponse_probleme("Aucun echo pour ce message (ECHO_INTROUVABLE)."),
        422: reponse_probleme("Message invalide (REQUETE_INVALIDE)."),
    },
    summary="Relire un message enregistré (appelant authentifié)",
)
async def lire(
    message: Annotated[Message, Path()],
    depot: DepotDep,
    parametres: ParametresDep,
    _appelant: AppelantDep,
) -> EchoReponse:
    return _reponse(await lire_echo(depot, message), parametres)
