"""Conformité de paiements à son contrat (E10 du plan BIL-008 ; décision Q10).

`openapi.yaml` du service reprend le contrat cible `docs/contrats/paiements.yaml` pour
`creerPaiement` et `lirePaiement` ; le schéma généré par FastAPI ne diverge pas du contrat.
"""

import secrets
from pathlib import Path
from typing import Any

import pytest
import yaml

from commun.contrat import differences_contrat
from commun.faux_jetons import EmetteurDeTest
from paiements.config import Parametres
from paiements.principal import creer_app

RACINE = Path(__file__).resolve().parents[4]
CONTRAT_SERVICE = RACINE / "services" / "paiements" / "openapi.yaml"
CONTRAT_CIBLE = RACINE / "docs" / "contrats" / "paiements.yaml"
METHODES = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
OPERATIONS = {"creerPaiement", "lirePaiement"}
SCHEMAS = {"PaiementCreation", "StatutPaiement", "Paiement"}


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


@pytest.mark.contract
def test_le_schema_genere_est_conforme_au_contrat() -> None:
    url = f"postgresql+asyncpg://paiements:{secrets.token_urlsafe(16)}@127.0.0.1:5432/paiements"
    app = creer_app(
        Parametres(database_url=url, consul_actif=False),
        verificateur_jetons=EmetteurDeTest().verificateur(),
    )
    contrat = _charger(CONTRAT_SERVICE)

    differences = differences_contrat(contrat, app.openapi())

    assert not differences, "paiements diverge de openapi.yaml :\n" + "\n".join(differences)
    operations = _operations(contrat)
    assert set(operations) == {"sante", *OPERATIONS}
    for nom in OPERATIONS:
        assert operations[nom][2]["security"] == [{"HTTPBearer": []}], nom


def test_les_contrats_des_services_reprennent_les_contrats_cibles() -> None:
    service = _charger(CONTRAT_SERVICE)
    cible = _charger(CONTRAT_CIBLE)
    operations_service = _operations(service)
    operations_cible = _operations(cible)

    differentes = sorted(
        nom for nom in OPERATIONS if operations_service.get(nom) != operations_cible.get(nom)
    )
    schemas_differents = sorted(
        nom
        for nom in SCHEMAS
        if service["components"]["schemas"].get(nom) != cible["components"]["schemas"].get(nom)
    )

    assert differentes == []
    assert schemas_differents == []
    # 503 BASE_INDISPONIBLE de la décision Q10.
    reponses = operations_service["creerPaiement"][2]["responses"]
    assert "BASE_INDISPONIBLE" in reponses["503"]["description"]
