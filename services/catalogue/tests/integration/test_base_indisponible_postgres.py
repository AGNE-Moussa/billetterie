"""E5 (BIL-004, décision Q6) : base injoignable, 503 `BASE_INDISPONIBLE`, puis retour à 200.

Le conteneur PostgreSQL du module est mis en pause (`docker pause`) pendant que le service
tourne, puis repris : le service répond 503 pendant la pause et 200 après, sans redémarrer.
Chaque appel est borné (fixture `borner`) : une requête qui reste bloquée sur la base fait
échouer le test par une assertion.
"""

from typing import Any

import httpx
import pytest
from testcontainers.community.postgres import PostgresContainer

pytestmark = pytest.mark.anyio

DELAI_PENDANT_LA_PAUSE = 60.0


async def test_une_lecture_repond_503_quand_la_base_tombe_puis_200_a_son_retour(
    client_public: httpx.AsyncClient, postgres: PostgresContainer, borner: Any
) -> None:
    conteneur = postgres.get_wrapped_container()
    conteneur.pause()
    try:
        pendant = await borner(
            "GET /api/v1/events, base en pause",
            client_public.get("/api/v1/events"),
            DELAI_PENDANT_LA_PAUSE,
        )
    finally:
        conteneur.unpause()

    apres = await borner("GET /api/v1/events, base reprise", client_public.get("/api/v1/events"))

    assert pendant.status_code == 503, pendant.text
    assert pendant.headers["content-type"].startswith("application/problem+json")
    assert pendant.json()["code"] == "BASE_INDISPONIBLE"
    assert pendant.json()["status"] == 503
    assert "postgresql" not in pendant.text.lower()
    assert apres.status_code == 200, apres.text
