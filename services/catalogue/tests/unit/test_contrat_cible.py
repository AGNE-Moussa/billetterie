"""Le contrat de catalogue reprend le contrat cible BIL-002, sans annulation ni modification
(CA1, décisions Q1 et Q2 du ticket BIL-004)."""

from pathlib import Path
from typing import Any

import yaml

RACINE = Path(__file__).resolve().parents[4]
CONTRAT_SERVICE = RACINE / "services" / "catalogue" / "openapi.yaml"
CONTRAT_CIBLE = RACINE / "docs" / "contrats" / "catalogue.yaml"
METHODES = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


def _charger(fichier: Path) -> dict[str, Any]:
    contenu: dict[str, Any] = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    return contenu


def _operations(contrat: dict[str, Any]) -> dict[str, tuple[str, str, dict[str, Any]]]:
    return {
        operation["operationId"]: (chemin, methode, operation)
        for chemin, item in contrat["paths"].items()
        for methode, operation in item.items()
        if methode in METHODES
    }


def test_le_contrat_de_catalogue_reprend_les_routes_du_contrat_cible_sans_annulation() -> None:
    service = _operations(_charger(CONTRAT_SERVICE))
    cible = _operations(_charger(CONTRAT_CIBLE))

    absentes = sorted(set(service) - set(cible))
    differentes = sorted(nom for nom in set(service) & set(cible) if service[nom] != cible[nom])

    assert absentes == []
    assert differentes == []
    assert "annulerSeance" not in service
    assert not any(chemin.endswith("/cancellation") for chemin, _, _ in service.values())
    assert {methode for _, methode, _ in service.values()} <= {"get", "post"}
    assert len(service) == 11
