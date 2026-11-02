"""E9 (BIL-006) : les réponses réelles, sur vraie base et vrai Redis, valident le contrat.

Schémas `Place`, `PlacePage`, `Verrou` et `Probleme` de services/billets/openapi.yaml.
"""

import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.anyio


async def test_les_reponses_reelles_valident_le_schema_du_contrat(
    plateforme: Any, seance: Any, composants: dict[str, Any], outils: Any
) -> None:
    place = seance.places["A1"]

    page = outils.exiger_statut(await plateforme.places(seance.id), 200, "listerPlaces")
    verrou = outils.exiger_statut(
        await plateforme.verrouiller(seance.id, place, uuid.uuid4()), 200, "verrouillerPlace"
    )
    introuvable = await plateforme.verrouiller(seance.id, uuid.uuid4(), uuid.uuid4())
    prise = await plateforme.verrouiller(seance.id, place, uuid.uuid4())
    invalide = await plateforme.instance_1.put(
        f"{outils.route_places}/pas-un-uuid/lock",
        json={"seance_id": str(seance.id), "commande_id": str(uuid.uuid4())},
    )

    assert outils.erreurs_schema(page, "PlacePage", composants) == []
    assert page["elements"], "page vide : aucun élément Place à valider"
    for element in page["elements"]:
        assert outils.erreurs_schema(element, "Place", composants) == []
    assert outils.erreurs_schema(verrou, "Verrou", composants) == []
    for reponse, statut, code in (
        (introuvable, 404, "SEAT_NOT_FOUND"),
        (prise, 409, "SEAT_ALREADY_TAKEN"),
        (invalide, 422, "REQUETE_INVALIDE"),
    ):
        outils.exiger_probleme(reponse, statut, code, f"réponse {statut}")
        assert outils.erreurs_schema(reponse.json(), "Probleme", composants) == []
