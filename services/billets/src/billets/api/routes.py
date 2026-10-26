"""Routes du service : santé seulement."""

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from billets.api.dependances import SessionDep
from billets.api.schemas import Sante
from commun.erreurs import ErreurMetier, reponse_probleme

routeur_sante = APIRouter(tags=["santé"])


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
