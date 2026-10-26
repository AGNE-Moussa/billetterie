"""Le schéma OpenAPI généré par chaque service doit être identique à son openapi.yaml."""

import importlib
import secrets
from pathlib import Path

import pytest
import yaml

from commun.contrat import differences_contrat

RACINE = Path(__file__).resolve().parents[2]
CONTRATS = sorted(RACINE.glob("services/*/openapi.yaml"))


@pytest.mark.contract
@pytest.mark.parametrize("contrat", CONTRATS, ids=[c.parent.name for c in CONTRATS])
def test_le_code_de_chaque_service_respecte_son_contrat(contrat: Path) -> None:
    nom = contrat.parent.name
    principal = importlib.import_module(f"{nom}.principal")
    config = importlib.import_module(f"{nom}.config")
    url = f"postgresql+asyncpg://{nom}:{secrets.token_urlsafe(16)}@127.0.0.1:5432/{nom}"
    app = principal.creer_app(config.Parametres(database_url=url))

    differences = differences_contrat(
        yaml.safe_load(contrat.read_text(encoding="utf-8")), app.openapi()
    )

    assert not differences, f"{nom} diverge de openapi.yaml :\n" + "\n".join(differences)
