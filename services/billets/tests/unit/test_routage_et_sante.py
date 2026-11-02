"""Routage Traefik et santé de billets (E8 du plan BIL-006, décisions Q6, Q21).

La santé démarre la vraie application (lifespan) sur SQLite en mémoire ; le magasin de verrous
est remplacé par un double injoignable.
"""

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from billets.api.dependances import obtenir_verrous
from billets.config import Parametres
from billets.principal import NOM_SERVICE, RESSOURCES, creer_app
from commun.faux_jetons import EmetteurDeTest
from commun.registre import VARIABLE_POINT_ENTREE, tags_sante_traefik, tags_traefik

pytestmark = pytest.mark.anyio

URL_REDIS = "redis://127.0.0.1:6379/0"


def test_billets_s_inscrit_avec_le_prefixe_seats(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(VARIABLE_POINT_ENTREE, raising=False)

    tags = tags_traefik(NOM_SERVICE, *RESSOURCES)
    sante = tags_sante_traefik(NOM_SERVICE, RESSOURCES[0])

    assert RESSOURCES == ("seats",)
    assert "traefik.http.routers.billets.rule=PathPrefix(`/api/v1/seats`)" in tags
    regles = [t for t in sante if t.startswith("traefik.http.routers.billets-sante.rule=")]
    assert len(regles) == 1
    assert "Path(`/api/v1/seats/health`)" in regles[0]
    assert any(t.endswith(".replacepath.path=/health") for t in sante), sante


async def test_la_sante_repond_200_quand_redis_est_injoignable(
    verrous: Any, emetteur: EmetteurDeTest
) -> None:
    verrous.injoignable = True
    config = Parametres(
        database_url="sqlite+aiosqlite://",
        redis_url=URL_REDIS,
        instance="billets-test",
        consul_actif=False,
    )
    app: FastAPI = creer_app(config, verificateur_jetons=emetteur.verificateur())
    app.dependency_overrides[obtenir_verrous] = lambda: verrous
    transport = httpx.ASGITransport(app=app)

    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        reponse = await client.get("/health")

    assert reponse.status_code == 200, reponse.text
    assert reponse.json() == {"statut": "ok"}
