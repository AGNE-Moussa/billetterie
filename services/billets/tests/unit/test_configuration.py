"""Durées du verrou et dépendances en configuration (E7 du plan BIL-006, décisions Q8, Q20)."""

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
import yaml
from pydantic import ValidationError

from billets.config import Parametres

pytestmark = pytest.mark.anyio

RACINE = Path(__file__).resolve().parents[4]
URL_BASE = "postgresql+asyncpg://test@127.0.0.1:5432/billets"
URL_REDIS = "redis://127.0.0.1:6379/0"
VARIABLES = ("DUREE_VERROU_RESERVATION", "DUREE_VERROU_CONFIRMATION", "REDIS_URL")


@pytest.fixture(autouse=True)
def _environnement_propre(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in VARIABLES:
        monkeypatch.delenv(variable, raising=False)


def test_les_durees_par_defaut_sont_600_et_3600_secondes() -> None:
    config = Parametres(database_url=URL_BASE, redis_url=URL_REDIS)

    assert config.duree_verrou_reservation == 600
    assert config.duree_verrou_confirmation == 3600


async def test_les_durees_se_lisent_dans_l_environnement(
    monkeypatch: pytest.MonkeyPatch,
    fabrique_app: Any,
    seance: Any,
    horloge: Any,
    entetes_service: dict[str, str],
) -> None:
    monkeypatch.setenv("DUREE_VERROU_RESERVATION", "120")
    monkeypatch.setenv("DUREE_VERROU_CONFIRMATION", "900")
    config = Parametres(database_url=URL_BASE, redis_url=URL_REDIS)
    assert (config.duree_verrou_reservation, config.duree_verrou_confirmation) == (120, 900)
    place = seance["A1"]
    corps = {"seance_id": str(seance.id), "commande_id": str(uuid4())}

    transport = httpx.ASGITransport(app=fabrique_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.put(
            f"/api/v1/seats/{place.id}/lock", json=corps, headers=entetes_service
        )

    assert reponse.status_code == 200, reponse.text
    expire_le = datetime.fromisoformat(reponse.json()["expire_le"])
    attendu = horloge.maintenant + timedelta(seconds=120)
    assert abs(expire_le - attendu) <= timedelta(seconds=2), (expire_le, attendu)


@pytest.mark.parametrize("valeur", ["0", "-5"])
def test_une_duree_nulle_ou_negative_est_refusee_au_demarrage(
    monkeypatch: pytest.MonkeyPatch, valeur: str
) -> None:
    monkeypatch.setenv("DUREE_VERROU_RESERVATION", valeur)

    with pytest.raises(ValidationError):
        Parametres(database_url=URL_BASE, redis_url=URL_REDIS)


def test_redis_url_est_obligatoire() -> None:
    with pytest.raises(ValidationError):
        Parametres(database_url=URL_BASE)


def test_le_compose_fournit_redis_et_rabbitmq_a_billets() -> None:
    compose: dict[str, Any] = yaml.safe_load((RACINE / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    # L'ancre billets-env est l'environnement de billets-migrations, repris par les instances.
    environnement = services["billets-migrations"]["environment"]
    exemple = (RACINE / ".env.example").read_text(encoding="utf-8").splitlines()

    assert "REDIS_URL" in environnement
    assert "RABBITMQ_URL" in environnement
    for instance in ("billets-1", "billets-2"):
        assert "REDIS_URL" in services[instance]["environment"], instance
        assert "RABBITMQ_URL" in services[instance]["environment"], instance
        assert {"redis", "rabbitmq"} <= set(services[instance]["depends_on"]), instance
    # .env.example : variables déclarées, sans aucune valeur.
    for ligne in exemple:
        trouve = re.fullmatch(r"(REDIS_URL|RABBITMQ_\w+|BILLETS_\w+)=(.*)", ligne.strip())
        if trouve:
            assert trouve.group(2) == "", ligne
