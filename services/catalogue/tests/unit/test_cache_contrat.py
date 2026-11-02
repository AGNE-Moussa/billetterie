"""En-tête X-Cache-Stale au contrat : sur le 200 des 7 lectures publiques, nulle part ailleurs,
et absent de docs/conventions.md (E8, décisions D1 et D6 du ticket BIL-005)."""

from pathlib import Path
from typing import Any

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[4]
CONTRATS = [
    RACINE / "services" / "catalogue" / "openapi.yaml",
    RACINE / "docs" / "contrats" / "catalogue.yaml",
]
CONVENTIONS = RACINE / "docs" / "conventions.md"
METHODES = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
EN_TETE = "X-Cache-Stale"
LECTURES = {
    "listerEvenements",
    "lireEvenement",
    "listerSeances",
    "lireSeance",
    "lireSeanceParId",
    "listerLieux",
    "lireLieu",
}


@pytest.mark.parametrize("contrat", CONTRATS, ids=lambda chemin: chemin.name)
def test_x_cache_stale_est_declare_sur_les_sept_lectures_et_nulle_part_ailleurs(
    contrat: Path,
) -> None:
    document: dict[str, Any] = yaml.safe_load(contrat.read_text(encoding="utf-8"))
    declarees: set[str] = set()
    ailleurs: list[str] = []

    for item in document["paths"].values():
        for methode, operation in item.items():
            if methode not in METHODES:
                continue
            for statut, reponse in operation["responses"].items():
                entetes = reponse.get("headers", {})
                if EN_TETE not in entetes:
                    continue
                if operation["operationId"] in LECTURES and str(statut) == "200":
                    assert entetes[EN_TETE]["schema"] == {"type": "string", "enum": ["true"]}
                    declarees.add(operation["operationId"])
                else:
                    ailleurs.append(f"{operation['operationId']} {statut}")

    assert declarees == LECTURES
    assert ailleurs == []
    assert EN_TETE not in CONVENTIONS.read_text(encoding="utf-8")
