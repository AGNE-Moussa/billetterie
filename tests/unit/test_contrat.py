"""Le comparateur de contrat signale toute divergence entre openapi.yaml et le code."""

import copy
from typing import Any

from commun.contrat import differences_contrat

CONTRAT: dict[str, Any] = {
    "openapi": "3.1.0",
    "paths": {
        "/api/v1/echos/{message}": {
            "get": {
                "parameters": [{"name": "message", "in": "path", "required": True}],
                "responses": {"200": {"description": "OK"}, "404": {"description": "Absent"}},
            }
        }
    },
}


def test_schema_identique_au_contrat() -> None:
    assert differences_contrat(CONTRAT, copy.deepcopy(CONTRAT)) == []


def test_route_absente_du_code() -> None:
    genere = copy.deepcopy(CONTRAT)
    del genere["paths"]["/api/v1/echos/{message}"]

    assert differences_contrat(CONTRAT, genere) == [
        "paths./api/v1/echos/{message} : dans le contrat, absent du code"
    ]


def test_route_ajoutee_dans_le_code() -> None:
    genere = copy.deepcopy(CONTRAT)
    genere["paths"]["/api/v1/echos"] = {"post": {}}

    assert differences_contrat(CONTRAT, genere) == [
        "paths./api/v1/echos : dans le code, absent du contrat"
    ]


def test_code_de_reponse_modifie() -> None:
    genere = copy.deepcopy(CONTRAT)
    reponses = genere["paths"]["/api/v1/echos/{message}"]["get"]["responses"]
    reponses["410"] = reponses.pop("404")

    assert differences_contrat(CONTRAT, genere) == [
        "paths./api/v1/echos/{message}.get.responses.404 : dans le contrat, absent du code",
        "paths./api/v1/echos/{message}.get.responses.410 : dans le code, absent du contrat",
    ]


def test_parametre_modifie() -> None:
    genere = copy.deepcopy(CONTRAT)
    genere["paths"]["/api/v1/echos/{message}"]["get"]["parameters"][0]["required"] = False

    assert differences_contrat(CONTRAT, genere) == [
        "paths./api/v1/echos/{message}.get.parameters[0].required : contrat True, code False"
    ]
