"""Le contrat de catalogue reprend le contrat cible BIL-002 (CA1, décisions Q1 et Q2 du ticket
BIL-004), annulation de séance comprise depuis BIL-011 (E1)."""

import secrets
from pathlib import Path
from typing import Any

import pytest
import yaml

from catalogue.config import Parametres
from catalogue.principal import creer_app
from commun.contrat import differences_contrat
from commun.faux_jetons import EmetteurDeTest

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


def test_le_contrat_de_catalogue_reprend_annulerSeance_du_contrat_cible() -> None:  # noqa: N802
    """BIL-011 (E1) : annulerSeance recopiée du contrat cible, 503 BASE_INDISPONIBLE compris ;
    toutes les opérations du contrat cible sont reprises à l'identique."""
    service = _operations(_charger(CONTRAT_SERVICE))
    cible = _operations(_charger(CONTRAT_CIBLE))

    absentes = sorted(set(service) - set(cible))
    differentes = sorted(nom for nom in set(service) & set(cible) if service[nom] != cible[nom])

    assert absentes == []
    assert differentes == []
    assert "annulerSeance" in service
    assert "annulerSeance" in cible
    assert service["annulerSeance"] == cible["annulerSeance"]
    chemin, methode, operation = service["annulerSeance"]
    assert chemin == "/api/v1/events/{evenement_id}/shows/{seance_id}/cancellation"
    assert methode == "post"
    assert set(operation["responses"]) >= {"200", "401", "403", "404", "409", "422", "503"}
    assert "BASE_INDISPONIBLE" in operation["responses"]["503"]["description"]
    assert {methode for _, methode, _ in service.values()} <= {"get", "post"}
    assert len(service) == 12


@pytest.mark.contract
def test_le_schema_genere_par_fastapi_est_conforme_au_contrat() -> None:
    url = f"postgresql+asyncpg://catalogue:{secrets.token_urlsafe(16)}@127.0.0.1:5432/catalogue"
    app = creer_app(
        Parametres(database_url=url, consul_actif=False),
        verificateur_jetons=EmetteurDeTest().verificateur(),
    )

    differences = differences_contrat(_charger(CONTRAT_SERVICE), app.openapi())

    assert not differences, "catalogue diverge de openapi.yaml :\n" + "\n".join(differences)
    assert "annulerSeance" in _operations(app.openapi())
