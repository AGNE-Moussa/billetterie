"""Erreurs au format Problem Details (RFC 9457), avec un code métier stable.

À déplacer dans libs/commun quand le code commun des erreurs sera écrit (BIL-F11).
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from echo.domaine.echos import EchoDejaExistant, EchoIntrouvable

TYPE_MEDIA = "application/problem+json"


class Probleme(BaseModel):
    type: str = Field(default="about:blank")
    title: str
    status: int
    detail: str
    code: str = Field(description="Code métier stable, par exemple ECHO_INTROUVABLE.")
    erreurs: list[dict[str, Any]] | None = Field(
        default=None, description="Détail des champs invalides (code REQUETE_INVALIDE)."
    )


def reponse_probleme(description: str) -> dict[str, Any]:
    """Entrée `responses` d'une route : documente une erreur Problem Details."""
    return {"model": Probleme, "description": description}


def _reponse(probleme: Probleme) -> JSONResponse:
    return JSONResponse(
        probleme.model_dump(exclude_none=True), status_code=probleme.status, media_type=TYPE_MEDIA
    )


async def _echo_introuvable(_requete: Request, erreur: Exception) -> JSONResponse:
    return _reponse(
        Probleme(title="Echo introuvable", status=404, detail=str(erreur), code="ECHO_INTROUVABLE")
    )


async def _echo_deja_existant(_requete: Request, erreur: Exception) -> JSONResponse:
    return _reponse(
        Probleme(title="Echo déjà existant", status=409, detail=str(erreur), code="ECHO_EXISTANT")
    )


async def _requete_invalide(_requete: Request, erreur: Exception) -> JSONResponse:
    assert isinstance(erreur, RequestValidationError)
    erreurs = [
        {"champ": ".".join(str(partie) for partie in e["loc"]), "message": e["msg"]}
        for e in erreur.errors()
    ]
    return _reponse(
        Probleme(
            title="Requête invalide",
            status=422,
            detail="Un ou plusieurs champs sont invalides.",
            code="REQUETE_INVALIDE",
            erreurs=erreurs,
        )
    )


def _documenter_type_media(schema: dict[str, Any]) -> dict[str, Any]:
    """Annonce application/problem+json pour les erreurs : FastAPI les documente en JSON simple."""
    reference = "#/components/schemas/Probleme"
    for operations in schema.get("paths", {}).values():
        for operation in operations.values():
            for reponse in operation.get("responses", {}).values():
                contenu = reponse.get("content", {})
                if contenu.get("application/json", {}).get("schema", {}).get("$ref") == reference:
                    contenu[TYPE_MEDIA] = contenu.pop("application/json")
    return schema


def installer_gestionnaires(app: FastAPI) -> None:
    app.add_exception_handler(EchoIntrouvable, _echo_introuvable)
    app.add_exception_handler(EchoDejaExistant, _echo_deja_existant)
    app.add_exception_handler(RequestValidationError, _requete_invalide)

    openapi_par_defaut = app.openapi

    def openapi() -> dict[str, Any]:
        return _documenter_type_media(openapi_par_defaut())

    app.openapi = openapi  # type: ignore[method-assign]
