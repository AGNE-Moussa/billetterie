"""Données de ticketing.show.scheduled (E6, décision Q5 du ticket BIL-004), sans base."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import jsonschema

from catalogue.domaine.catalogue import (
    EVENEMENT_SEANCE_PROGRAMMEE,
    Categorie,
    Evenement,
    Lieu,
    Rang,
    Seance,
    donnees_seance_programmee,
)

RACINE = Path(__file__).resolve().parents[4]
SCHEMA = RACINE / "docs" / "evenements" / f"{EVENEMENT_SEANCE_PROGRAMMEE}.json"


def _schema_data() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(SCHEMA.read_text(encoding="utf-8"))
    return {"$schema": schema["$schema"], **schema["properties"]["data"]}


def test_les_donnees_de_l_evenement_reprennent_la_seance_l_evenement_et_le_lieu() -> None:
    cree_le = datetime(2026, 10, 1, tzinfo=UTC)
    evenement = Evenement(uuid4(), "Concert de test", "Description synthétique", cree_le)
    lieu = Lieu(uuid4(), "Salle de test", "1 rue de l'Exemple", "Villetest", cree_le)
    fosse = Categorie(uuid4(), "Fosse", 4500, [Rang("A", 10), Rang("B", 12)])
    balcon = Categorie(uuid4(), "Balcon", 3000, [Rang("C", 8)])
    debut = datetime(2026, 12, 1, 20, 0, tzinfo=UTC) + timedelta(days=30)
    seance = Seance(uuid4(), evenement.id, lieu.id, debut, False, [fosse, balcon])

    data = donnees_seance_programmee(seance, evenement, lieu)

    jsonschema.Draft202012Validator(
        _schema_data(), format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    ).validate(data)
    assert data["seance_id"] == str(seance.id)
    assert data["evenement_id"] == str(evenement.id)
    assert data["evenement_nom"] == "Concert de test"
    assert data["lieu_id"] == str(lieu.id)
    assert data["lieu_nom"] == "Salle de test"
    assert data["ville"] == "Villetest"
    assert datetime.fromisoformat(data["debut"]) == debut
    assert datetime.fromisoformat(data["debut"]).utcoffset() is not None
    assert [c["categorie_id"] for c in data["categories"]] == [str(fosse.id), str(balcon.id)]
    assert data["categories"][0]["rangs"] == [
        {"rang": "A", "nombre_places": 10},
        {"rang": "B", "nombre_places": 12},
    ]
