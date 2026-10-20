"""Erreurs au format Problem Details (RFC 9457), avec un code métier stable.

Toutes les erreurs d'un service sortent avec le même corps `application/problem+json` :
`type`, `title`, `status`, `detail`, `code`, `correlation_id`. Une erreur imprévue donne un
500 générique : la trace part dans les journaux, jamais au client.

Utilisation dans un service :

    class PlaceDejaPrise(ErreurMetier):
        def __init__(self, place: str) -> None:
            super().__init__("SEAT_ALREADY_TAKEN", 409, f"La place {place} est déjà prise.")

    installer_erreurs(app)
"""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from commun.correlation import ENTETE, correlation_id

journal = logging.getLogger(__name__)

TYPE_MEDIA = "application/problem+json"
# Erreurs produites par le framework lui-même (route ou méthode inconnue).
CODES_HTTP = {404: "RESSOURCE_INTROUVABLE", 405: "METHODE_NON_AUTORISEE"}


class Probleme(BaseModel):
    type: str = Field(default="about:blank")
    title: str
    status: int
    detail: str
    code: str = Field(description="Code métier stable, par exemple ECHO_INTROUVABLE.")
    correlation_id: str | None = Field(
        default=None, description="Identifiant de corrélation de la requête (X-Correlation-Id)."
    )
    erreurs: list[dict[str, Any]] | None = Field(
        default=None, description="Détail des champs invalides (code REQUETE_INVALIDE)."
    )


class ErreurMetier(Exception):
    """Erreur prévue par le métier, renvoyée au client avec son code et son statut."""

    def __init__(
        self,
        code: str,
        statut: int,
        detail: str,
        titre: str | None = None,
        entetes: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.statut = statut
        # En-têtes ajoutés à la réponse, par exemple WWW-Authenticate sur un 401.
        self.entetes = entetes or {}
        self.detail = detail
        self.titre = titre or HTTPStatus(statut).phrase


def reponse_probleme(description: str) -> dict[str, Any]:
    """Entrée `responses` d'une route : documente une erreur Problem Details."""
    return {"model": Probleme, "description": description}


def _reponse(statut: int, titre: str, detail: str, code: str, **extra: Any) -> JSONResponse:
    identifiant = correlation_id()
    probleme = Probleme(
        title=titre, status=statut, detail=detail, code=code, correlation_id=identifiant, **extra
    )
    reponse = JSONResponse(
        probleme.model_dump(exclude_none=True), status_code=statut, media_type=TYPE_MEDIA
    )
    if identifiant:
        # Le 500 est produit hors du middleware de corrélation : on pose l'en-tête ici.
        reponse.headers[ENTETE] = identifiant
    return reponse


async def _erreur_metier(_requete: Request, erreur: Exception) -> JSONResponse:
    assert isinstance(erreur, ErreurMetier)
    reponse = _reponse(erreur.statut, erreur.titre, erreur.detail, erreur.code)
    reponse.headers.update(erreur.entetes)
    return reponse


async def _requete_invalide(_requete: Request, erreur: Exception) -> JSONResponse:
    assert isinstance(erreur, RequestValidationError)
    erreurs = [
        {"champ": ".".join(str(partie) for partie in e["loc"]), "message": e["msg"]}
        for e in erreur.errors()
    ]
    return _reponse(
        422,
        "Requête invalide",
        "Un ou plusieurs champs sont invalides.",
        "REQUETE_INVALIDE",
        erreurs=erreurs,
    )


async def _erreur_http(_requete: Request, erreur: Exception) -> JSONResponse:
    assert isinstance(erreur, HTTPException)
    reponse = _reponse(
        erreur.status_code,
        HTTPStatus(erreur.status_code).phrase,
        str(erreur.detail),
        CODES_HTTP.get(erreur.status_code, "ERREUR_HTTP"),
    )
    reponse.headers.update(erreur.headers or {})
    return reponse


async def _erreur_imprevue(_requete: Request, _erreur: Exception) -> JSONResponse:
    journal.exception("Erreur non gérée")
    return _reponse(500, "Erreur interne", "Une erreur inattendue est survenue.", "ERREUR_INTERNE")


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


def installer_erreurs(app: FastAPI) -> None:
    """Branche les gestionnaires d'erreurs et corrige le type des erreurs dans l'OpenAPI."""
    app.add_exception_handler(ErreurMetier, _erreur_metier)
    app.add_exception_handler(RequestValidationError, _requete_invalide)
    app.add_exception_handler(HTTPException, _erreur_http)
    app.add_exception_handler(Exception, _erreur_imprevue)

    openapi_par_defaut = app.openapi

    def openapi() -> dict[str, Any]:
        return _documenter_type_media(openapi_par_defaut())

    app.openapi = openapi  # type: ignore[method-assign]
