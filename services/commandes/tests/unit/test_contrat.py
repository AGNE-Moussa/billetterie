"""Conformité de commandes à son contrat (E10 du plan BIL-008 ; décisions Q10, Q18).

`openapi.yaml` du service reprend le contrat cible `docs/contrats/commandes.yaml` pour les
quatre opérations du ticket ; le schéma généré par FastAPI ne diverge pas du contrat.
"""

import secrets
from pathlib import Path
from typing import Any

import pytest
import yaml

from commandes.config import Parametres
from commandes.principal import creer_app
from commun.contrat import differences_contrat
from commun.faux_jetons import EmetteurDeTest

RACINE = Path(__file__).resolve().parents[4]
CONTRAT_SERVICE = RACINE / "services" / "commandes" / "openapi.yaml"
CONTRAT_CIBLE = RACINE / "docs" / "contrats" / "commandes.yaml"
METHODES = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
OPERATIONS = {"creerCommande", "listerCommandes", "lireCommande", "payerCommande"}
SCHEMAS = {
    "CommandeCreation",
    "PaiementCommande",
    "StatutCommande",
    "LigneCommande",
    "Commande",
    "CommandePage",
}


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
    url = f"postgresql+asyncpg://commandes:{secrets.token_urlsafe(16)}@127.0.0.1:5432/commandes"
    app = creer_app(
        Parametres(database_url=url, consul_actif=False),
        verificateur_jetons=EmetteurDeTest().verificateur(),
    )
    contrat = _charger(CONTRAT_SERVICE)

    differences = differences_contrat(contrat, app.openapi())

    assert not differences, "commandes diverge de openapi.yaml :\n" + "\n".join(differences)
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
    # 503 de la décision Q10 sur les quatre routes ; Billets au 503 de payerCommande (Q18).
    for nom in OPERATIONS:
        assert "503" in operations_service[nom][2]["responses"], nom
    paiement = operations_service["payerCommande"][2]["responses"]["503"]["description"]
    assert "BASE_INDISPONIBLE" in paiement
    assert "Billets" in paiement
