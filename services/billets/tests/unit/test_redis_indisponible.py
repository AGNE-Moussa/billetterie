"""Redis injoignable : échec fermé en 503 VERROU_INDISPONIBLE (E9 du plan BIL-006, Q9, Q10)."""

from typing import Any
from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.anyio


async def test_redis_injoignable_le_verrouillage_renvoie_503_sans_verrou(
    client: httpx.AsyncClient, seance: Any, verrous: Any, entetes_service: dict[str, str]
) -> None:
    place = seance["A1"]
    verrous.injoignable = True
    corps = {"seance_id": str(seance.id), "commande_id": str(uuid4())}

    reponse = await client.put(
        f"/api/v1/seats/{place.id}/lock", json=corps, headers=entetes_service
    )

    assert reponse.status_code == 503, reponse.text
    assert reponse.headers["content-type"] == "application/problem+json"
    assert reponse.json()["code"] == "VERROU_INDISPONIBLE"
    assert "Traceback" not in reponse.text
    verrous.injoignable = False
    assert verrous.cles() == {}


async def test_redis_injoignable_la_disponibilite_renvoie_503(
    client: httpx.AsyncClient, seance: Any, verrous: Any
) -> None:
    verrous.injoignable = True

    reponse = await client.get("/api/v1/seats", params={"seance_id": str(seance.id)})

    assert reponse.status_code == 503, reponse.text
    assert reponse.headers["content-type"] == "application/problem+json"
    probleme = reponse.json()
    assert probleme["code"] == "VERROU_INDISPONIBLE"
    assert "elements" not in probleme
