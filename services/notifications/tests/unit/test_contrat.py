"""Conformité de notifications à son contrat (E5 du plan BIL-009) : aucune route HTTP ajoutée,
le schéma généré par FastAPI ne diverge pas de `openapi.yaml`."""

import secrets
from pathlib import Path
from typing import Any

import pytest
import yaml

from commun.contrat import differences_contrat
from commun.faux_jetons import EmetteurDeTest
from notifications.config import Parametres
from notifications.principal import creer_app

RACINE = Path(__file__).resolve().parents[4]
CONTRAT = RACINE / "services" / "notifications" / "openapi.yaml"


@pytest.mark.contract
def test_le_schema_genere_par_notifications_est_conforme_au_contrat() -> None:
    mot_de_passe = secrets.token_urlsafe(16)
    url = f"postgresql+asyncpg://notifications:{mot_de_passe}@127.0.0.1:5432/notifications"
    config = Parametres(database_url=url, consul_actif=False)
    app = creer_app(config, verificateur_jetons=EmetteurDeTest().verificateur())
    contrat: dict[str, Any] = yaml.safe_load(CONTRAT.read_text(encoding="utf-8"))

    differences = differences_contrat(contrat, app.openapi())

    assert not differences, "notifications diverge de openapi.yaml :\n" + "\n".join(differences)
    # Aucune route ajoutée par BIL-009 : la santé seule.
    assert set(contrat["paths"]) == {"/health"}
    assert set(app.openapi()["paths"]) == {"/health"}
