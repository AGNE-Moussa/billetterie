"""E9 (BIL-006, décisions Q9 et Q11) : Redis arrêté ou base injoignable, 503 sans trace.

Redis : conteneur propre au test, arrêté pendant que l'application tourne (`DELAI_REDIS=0.5`) ;
le verrouillage répond `503 VERROU_INDISPONIBLE` en moins de 2 s.

Base : le PostgreSQL du module est mis en pause (`docker pause`) puis repris ; les deux routes
des places répondent `503 BASE_INDISPONIBLE` et le PUT ne crée aucune clé Redis.
"""

import time
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from billets.principal import creer_app

pytestmark = pytest.mark.anyio

IMAGE_REDIS = "redis:7.4.6-alpine"
DELAI_REDIS = 0.5
DELAI_BASE = 1.0
REPONSE_REDIS_MAXIMALE = 2.0
# Borne d'une réponse pendant la pause de la base : delai_base + 5 s (comme le catalogue).
REPONSE_BASE_MAXIMALE = DELAI_BASE + 5.0


@pytest.fixture
def redis_jetable() -> Iterator[DockerContainer]:
    """Redis propre au test : il peut être arrêté sans gêner les autres cas du module."""
    conteneur = (
        DockerContainer(IMAGE_REDIS)
        .with_exposed_ports(6379)
        .waiting_for(LogMessageWaitStrategy("Ready to accept connections"))
    )
    with conteneur:
        yield conteneur


@asynccontextmanager
async def _service(
    database_url: str, redis_url: str, emetteur: Any, outils: Any, **reglages: Any
) -> AsyncIterator[httpx.AsyncClient]:
    """Une instance sous lifespan et son client, avec le jeton du client `services`."""
    app = creer_app(
        outils.parametres_billets(database_url, redis_url=redis_url, **reglages),
        verificateur_jetons=emetteur.verificateur(),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers=outils.entetes_service(emetteur),
            timeout=60.0,
        ) as client,
    ):
        yield client


async def test_redis_arrete_le_verrouillage_renvoie_503_dans_le_delai(
    database_url: str,
    seance: Any,
    redis_jetable: DockerContainer,
    emetteur: Any,
    outils: Any,
) -> None:
    url = outils.url_redis(redis_jetable)
    async with _service(database_url, url, emetteur, outils, delai_redis=DELAI_REDIS) as client:
        redis_jetable.get_wrapped_container().stop()
        debut = time.monotonic()
        reponse = await outils.borne(
            "PUT .../lock, Redis arrêté",
            client.put(
                f"{outils.route_places}/{seance.places['A1']}/lock",
                json={"seance_id": str(seance.id), "commande_id": str(uuid.uuid4())},
            ),
        )
        duree = time.monotonic() - debut

    outils.exiger_probleme(reponse, 503, "VERROU_INDISPONIBLE", "PUT .../lock, Redis arrêté")
    assert duree < REPONSE_REDIS_MAXIMALE, f"réponse en {duree:.2f} s"
    assert "Traceback" not in reponse.text
    assert url not in reponse.text


@pytest.mark.parametrize("operation", ["listerPlaces", "verrouillerPlace"])
async def test_base_injoignable_les_routes_des_places_renvoient_503(
    operation: str,
    database_url: str,
    redis_url: str,
    postgres: PostgresContainer,
    seance: Any,
    observateur: Any,
    emetteur: Any,
    outils: Any,
) -> None:
    async with _service(database_url, redis_url, emetteur, outils, delai_base=DELAI_BASE) as client:
        if operation == "listerPlaces":
            appel = client.get(outils.route_places, params={"seance_id": str(seance.id)})
        else:
            appel = client.put(
                f"{outils.route_places}/{seance.places['A1']}/lock",
                json={"seance_id": str(seance.id), "commande_id": str(uuid.uuid4())},
            )
        conteneur = postgres.get_wrapped_container()
        conteneur.pause()
        try:
            reponse = await outils.borne(
                f"{operation}, base en pause", appel, REPONSE_BASE_MAXIMALE
            )
        finally:
            conteneur.unpause()

    outils.exiger_probleme(reponse, 503, "BASE_INDISPONIBLE", f"{operation}, base en pause")
    assert "postgresql" not in reponse.text.lower()
    assert await observateur.cles() == []
