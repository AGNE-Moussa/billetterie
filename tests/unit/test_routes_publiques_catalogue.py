"""Lectures du catalogue publiques pour le vérificateur de la gateway (CA3 du plan BIL-004).

Décision Q3 : valeur par défaut de ROUTES_PUBLIQUES dans compose.yaml (local) ; décision Q4 :
la santé sous un préfixe public est publique aussi (option a).

BIL-006 (décision Q6) : GET /api/v1/seats rejoint la valeur par défaut, sa santé avec.
"""

import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import yaml

from verificateur.routes_publiques import RoutePublique, analyser, est_publique

RACINE = Path(__file__).resolve().parents[2]


def _routes_publiques_locales() -> tuple[RoutePublique, ...]:
    compose: dict[str, Any] = yaml.safe_load((RACINE / "compose.yaml").read_text(encoding="utf-8"))
    valeur = str(compose["services"]["verificateur"]["environment"]["ROUTES_PUBLIQUES"])
    defaut = re.fullmatch(r"\$\{ROUTES_PUBLIQUES:-(.*)\}", valeur)
    assert defaut is not None, valeur
    return analyser(defaut.group(1))


PUBLIQUES = [
    ("GET", "/api/v1/events"),
    ("GET", f"/api/v1/events/{uuid4()}/shows/{uuid4()}"),
    ("GET", f"/api/v1/shows/{uuid4()}"),
    ("GET", "/api/v1/venues?page=2"),
]
NON_PUBLIQUES = [
    ("POST", "/api/v1/events"),
    ("POST", "/api/v1/venues"),
    ("POST", f"/api/v1/events/{uuid4()}/shows"),
    ("GET", "/api/v1/showsX"),
    ("GET", "/api/v1/orders"),
]


@pytest.mark.parametrize(("methode", "uri"), PUBLIQUES + NON_PUBLIQUES)
def test_les_lectures_du_catalogue_sont_publiques_pour_le_verificateur(
    methode: str, uri: str
) -> None:
    routes = _routes_publiques_locales()

    assert est_publique(routes, methode, uri) is ((methode, uri) in PUBLIQUES)
    # Sans valeur par défaut, aucune route n'est publique : le cas public doit être couvert.
    assert routes


def test_la_sante_du_catalogue_suit_la_regle_retenue_pour_les_prefixes_publics() -> None:
    routes = _routes_publiques_locales()

    assert est_publique(routes, "GET", "/api/v1/events/health") is True


# --- BIL-006, E8 : disponibilité des places publique (décision Q6) ------------------------------

PLACES_PUBLIQUES = [
    ("GET", f"/api/v1/seats?seance_id={uuid4()}"),
    ("GET", "/api/v1/seats/health"),
]
PLACES_NON_PUBLIQUES = [
    ("PUT", f"/api/v1/seats/{uuid4()}/lock"),
    ("GET", "/api/v1/seatsX"),
]


@pytest.mark.parametrize(("methode", "uri"), PLACES_PUBLIQUES + PLACES_NON_PUBLIQUES)
def test_la_disponibilite_des_places_est_publique_pour_le_verificateur(
    methode: str, uri: str
) -> None:
    routes = _routes_publiques_locales()

    assert est_publique(routes, methode, uri) is ((methode, uri) in PLACES_PUBLIQUES)
    # Les préfixes du catalogue restent publics.
    for methode_catalogue, uri_catalogue in PUBLIQUES:
        assert est_publique(routes, methode_catalogue, uri_catalogue) is True
