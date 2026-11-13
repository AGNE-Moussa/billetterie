"""Conformité de billets à son contrat (E9 du plan BIL-006).

`openapi.yaml` du service reprend le contrat cible `docs/contrats/billets.yaml` (BIL-002) pour
`listerPlaces` et `verrouillerPlace` ; le schéma généré par FastAPI ne diverge pas du contrat.
"""

import secrets
from pathlib import Path
from typing import Any

import pytest
import yaml

from billets.config import Parametres
from billets.principal import creer_app
from commun.contrat import differences_contrat
from commun.faux_jetons import EmetteurDeTest

RACINE = Path(__file__).resolve().parents[4]
CONTRAT_SERVICE = RACINE / "services" / "billets" / "openapi.yaml"
CONTRAT_CIBLE = RACINE / "docs" / "contrats" / "billets.yaml"
METHODES = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
OPERATIONS = {"listerPlaces", "verrouillerPlace"}
SCHEMAS = {"Place", "PlacePage", "VerrouCreation", "Verrou"}


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
def test_le_schema_genere_par_billets_est_conforme_au_contrat() -> None:
    url = f"postgresql+asyncpg://billets:{secrets.token_urlsafe(16)}@127.0.0.1:5432/billets"
    config = Parametres(
        database_url=url,
        redis_url="redis://127.0.0.1:6379/0",
        # Clé QR synthétique, non réaliste (décision Q6 de BIL-009 : au moins 32 caractères).
        qr_cle_signature="cle-de-test-" * 3,
        consul_actif=False,
    )
    app = creer_app(config, verificateur_jetons=EmetteurDeTest().verificateur())
    contrat = _charger(CONTRAT_SERVICE)

    differences = differences_contrat(contrat, app.openapi())

    assert not differences, "billets diverge de openapi.yaml :\n" + "\n".join(differences)
    operations = _operations(contrat)
    assert set(operations) == {"sante", *OPERATIONS}
    assert "security" not in operations["listerPlaces"][2]
    assert operations["verrouillerPlace"][2]["security"] == [{"HTTPBearer": []}]


def test_les_routes_de_billets_reprennent_le_contrat_cible() -> None:
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
