"""E9 (BIL-005, Q5, Q6) : Redis en pause, le catalogue reste disponible depuis la base.

Le conteneur Redis du module est mis en pause (`docker pause`) ; chaque appel pendant la pause
est borné à delai_base + 5 s. Un témoin vérifie d'abord que le cache est actif (clé
`catalogue:cache:*`) : sans cache, la pause de Redis ne prouverait rien.
"""

from typing import Any

import anyio
import pytest

from catalogue.api.routes import EN_TETE_CACHE_PERIME

pytestmark = pytest.mark.anyio


async def test_redis_en_pause_la_lecture_repond_200_depuis_la_base(
    plateforme: Any, cache_redis: Any, redis: Any, en_pause: Any, borner: Any
) -> None:
    chemins = await plateforme.semer_lectures()
    await cache_redis.vider()
    assert (await plateforme.public.get(chemins["listerLieux"])).status_code == 200
    await cache_redis.exiger_rempli("après GET /api/v1/venues, avant la pause de Redis")

    with en_pause(redis):
        reponses = {
            operation: await borner(
                f"GET {chemin}, Redis en pause",
                plateforme.public.get(chemin),
                plateforme.delai_lecture,
            )
            for operation, chemin in chemins.items()
        }

    for operation, reponse in reponses.items():
        assert reponse.status_code == 200, f"{operation} : {reponse.text}"
        assert EN_TETE_CACHE_PERIME not in reponse.headers, operation


async def test_redis_en_pause_une_creation_repond_201_et_la_relecture_la_montre(
    plateforme: Any, cache_redis: Any, redis: Any, en_pause: Any, borner: Any
) -> None:
    await plateforme.catalogue.evenement()
    await cache_redis.vider()
    assert (await plateforme.public.get("/api/v1/events")).status_code == 200
    await cache_redis.exiger_rempli("après GET /api/v1/events, avant la pause de Redis")

    with en_pause(redis):
        creation = await borner(
            "POST /api/v1/events, Redis en pause",
            plateforme.admin.post("/api/v1/events", json=plateforme.catalogue.EVENEMENT),
            plateforme.delai_lecture,
        )
        relecture = await borner(
            "GET /api/v1/events, Redis en pause",
            plateforme.public.get("/api/v1/events"),
            plateforme.delai_lecture,
        )

    assert creation.status_code == 201, creation.text
    assert relecture.status_code == 200, relecture.text
    assert creation.json()["id"] in [e["id"] for e in relecture.json()["elements"]]


async def test_au_retour_de_redis_le_cache_se_remplit_de_nouveau(
    plateforme: Any,
    redis: Any,
    postgres: Any,
    en_pause: Any,
    borner: Any,
    attente_fraicheur: float,
) -> None:
    evenement = await plateforme.catalogue.evenement()
    chemin = f"/api/v1/events/{evenement['id']}"
    with en_pause(redis):
        pendant = await borner(
            f"GET {chemin}, Redis en pause", plateforme.public.get(chemin), plateforme.delai_lecture
        )
    assert pendant.status_code == 200, pendant.text

    apres_retour = await borner(f"GET {chemin}, Redis repris", plateforme.public.get(chemin))
    assert apres_retour.status_code == 200, apres_retour.text
    await anyio.sleep(attente_fraicheur)
    with en_pause(postgres):
        relecture = await borner(
            f"GET {chemin}, base en pause", plateforme.public.get(chemin), plateforme.delai_lecture
        )

    assert relecture.status_code == 200, relecture.text
    assert relecture.headers.get_list(EN_TETE_CACHE_PERIME) == ["true"]
    assert relecture.content == apres_retour.content
