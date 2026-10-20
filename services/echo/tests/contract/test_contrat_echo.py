"""Le schéma OpenAPI généré par le code doit être identique au contrat openapi.yaml."""

from pathlib import Path

import pytest
import yaml

from commun.contrat import differences_contrat
from echo.config import Parametres
from echo.principal import creer_app

CONTRAT = Path(__file__).resolve().parents[2] / "openapi.yaml"


@pytest.mark.contract
def test_le_code_respecte_le_contrat() -> None:
    app = creer_app(Parametres(database_url="postgresql+asyncpg://contrat@localhost/echo"))
    contrat = yaml.safe_load(CONTRAT.read_text(encoding="utf-8"))

    differences = differences_contrat(contrat, app.openapi())

    assert not differences, "Le code diverge de openapi.yaml :\n" + "\n".join(differences)
