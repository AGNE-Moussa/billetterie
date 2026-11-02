"""Places créées à partir de ticketing.show.scheduled (E5 du plan BIL-006, décision Q5)."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import jsonschema

from billets.domaine.places import EVENEMENT_SEANCE_PROGRAMMEE, places_de_la_seance

RACINE = Path(__file__).resolve().parents[4]
SCHEMA = RACINE / "docs" / "evenements" / f"{EVENEMENT_SEANCE_PROGRAMMEE}.json"


def _schema_data() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(SCHEMA.read_text(encoding="utf-8"))
    return {"$schema": schema["$schema"], **schema["properties"]["data"]}


def test_les_places_d_une_seance_sont_numerotees_de_un_a_nombre_places_par_rang(
    donnees_seance: Callable[[UUID, UUID, UUID], dict[str, Any]],
) -> None:
    seance_id, fosse, balcon = uuid4(), uuid4(), uuid4()
    data = donnees_seance(seance_id, fosse, balcon)
    # Le jeu de données du test respecte le schéma de l'événement.
    jsonschema.Draft202012Validator(
        _schema_data(), format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    ).validate(data)

    places = places_de_la_seance(data)

    assert len(places) == 27
    assert {p.seance_id for p in places} == {seance_id}
    par_rang: dict[str, list[int]] = {}
    for place in places:
        par_rang.setdefault(place.rang, []).append(place.numero)
    assert {rang: sorted(numeros) for rang, numeros in par_rang.items()} == {
        "A": list(range(1, 11)),
        "B": list(range(1, 13)),
        "C": list(range(1, 6)),
    }
    assert {p.categorie_id for p in places if p.rang in ("A", "B")} == {fosse}
    assert {p.categorie_id for p in places if p.rang == "C"} == {balcon}
