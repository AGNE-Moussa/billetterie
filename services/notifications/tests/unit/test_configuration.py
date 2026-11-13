"""Configuration et compose de notifications (E5 du plan BIL-009, H2, décision Q10)."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from notifications.config import Parametres

RACINE = Path(__file__).resolve().parents[4]
URL_BASE = "postgresql+asyncpg://test@127.0.0.1:5432/notifications"
VARIABLES = ("SMTP_HOTE", "SMTP_PORT", "SMTP_DELAI", "SMTP_EXPEDITEUR", "RABBITMQ_URL")


@pytest.fixture(autouse=True)
def _environnement_propre(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in VARIABLES:
        monkeypatch.delenv(variable, raising=False)


def test_la_configuration_de_notifications_se_lit_dans_l_environnement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defaut = Parametres(database_url=URL_BASE)
    assert (defaut.smtp_hote, defaut.smtp_port) == ("mailpit", 1025)
    assert defaut.smtp_delai > 0
    assert defaut.smtp_expediteur == "billetterie@exemple.test"
    # Sans URL de broker, pas de consommateur : facultative.
    assert defaut.rabbitmq_url is None

    monkeypatch.setenv("SMTP_HOTE", "smtp-test.exemple.test")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_DELAI", "1.5")
    monkeypatch.setenv("SMTP_EXPEDITEUR", "envois.test@exemple.test")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://test@127.0.0.1:5672/")
    lue = Parametres(database_url=URL_BASE)
    assert (lue.smtp_hote, lue.smtp_port, lue.smtp_delai) == ("smtp-test.exemple.test", 2525, 1.5)
    assert lue.smtp_expediteur == "envois.test@exemple.test"
    assert lue.rabbitmq_url == "amqp://test@127.0.0.1:5672/"

    # SMTP_DELAI > 0 : 0 refusé.
    monkeypatch.setenv("SMTP_DELAI", "0")
    with pytest.raises(ValidationError):
        Parametres(database_url=URL_BASE)


def test_mailpit_et_notifications_sont_declares_dans_le_compose() -> None:
    compose: dict[str, Any] = yaml.safe_load((RACINE / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    mailpit = services["mailpit"]
    assert mailpit["image"].startswith("axllent/mailpit:")
    assert "healthcheck" in mailpit
    ports = [str(p) for p in mailpit.get("ports", [])]
    assert ports
    assert all(p.startswith("127.0.0.1:") for p in ports), ports

    # L'ancre notifications-env est l'environnement de notifications-migrations.
    environnement = services["notifications-migrations"]["environment"]
    assert environnement["SMTP_HOTE"] == "mailpit"
    assert str(environnement["SMTP_PORT"]) == "1025"
    assert re.match(r"amqp://", str(environnement["RABBITMQ_URL"]))
    instance = services["notifications-1"]
    for variable in ("SMTP_HOTE", "SMTP_PORT", "RABBITMQ_URL"):
        assert instance["environment"][variable] == environnement[variable], variable
    dependances = instance["depends_on"]
    for service in ("mailpit", "rabbitmq"):
        assert dependances[service]["condition"] == "service_healthy", service
