"""Configuration de commandes : environnement, compose.yaml et .env.example (E9 du plan
BIL-008 ; décision Q23)."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from commandes.config import Parametres

RACINE = Path(__file__).resolve().parents[4]
URL_BASE = "postgresql+asyncpg://test@127.0.0.1:5432/commandes"
VARIABLES = ("URL_GATEWAY", "URL_JETON", "SERVICES_CLIENT_SECRET", "RABBITMQ_URL")


def test_la_configuration_de_commandes_se_lit_dans_l_environnement(
    monkeypatch: pytest.MonkeyPatch, environnement_propre: None
) -> None:
    monkeypatch.setenv("URL_GATEWAY", "http://gateway-de-test")
    monkeypatch.setenv("URL_JETON", "http://keycloak-de-test/token")
    monkeypatch.setenv("LIMITE_BILLETS_PAR_SEANCE", "4")
    config = Parametres(database_url=URL_BASE)
    assert (config.url_gateway, config.url_jeton, config.limite_billets_par_seance) == (
        "http://gateway-de-test",
        "http://keycloak-de-test/token",
        4,
    )

    compose: dict[str, Any] = yaml.safe_load((RACINE / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    # L'ancre commandes-env est l'environnement de commandes-migrations, repris par les instances.
    environnement = services["commandes-migrations"]["environment"]
    exemple = (RACINE / ".env.example").read_text(encoding="utf-8").splitlines()

    for instance in ("commandes-1", "commandes-2"):
        absentes = [v for v in VARIABLES if v not in services[instance]["environment"]]
        assert absentes == [], instance
    assert re.fullmatch(
        r"\$\{KEYCLOAK_SERVICES_SECRET:\?.+\}", str(environnement.get("SERVICES_CLIENT_SECRET"))
    ), environnement.get("SERVICES_CLIENT_SECRET")
    # .env.example : le secret est déclaré, sans valeur.
    assert "KEYCLOAK_SERVICES_SECRET=" in [ligne.strip() for ligne in exemple]
