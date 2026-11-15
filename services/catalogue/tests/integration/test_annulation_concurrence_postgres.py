"""BIL-011, E1 (H3) : annulations simultanées de la même séance (plan docs/test-plans/BIL-011.md).

Requêtes admin réellement simultanées (barrière `asyncio.Event`, puis `asyncio.gather`) sur la
vraie base migrée, 20 tours : le passage conditionnel `annulee = false` → true ne laisse passer
qu'une requête, qui seule publie `ticketing.show.cancelled`. Marqueur `concurrence` : joué par
`make test-concurrence`.
"""

import asyncio
from collections import Counter
from typing import Any

import httpx
import pytest

pytestmark = [pytest.mark.anyio, pytest.mark.concurrence]

TOURS = 20
TYPE = "ticketing.show.cancelled"


async def simultanees(nombre: int, appel: Any) -> list[httpx.Response]:
    depart = asyncio.Event()

    async def tache() -> httpx.Response:
        await depart.wait()
        return await appel()  # type: ignore[no-any-return]

    taches = [asyncio.create_task(tache()) for _ in range(nombre)]
    await asyncio.sleep(0)
    depart.set()
    return list(await asyncio.wait_for(asyncio.gather(*taches), timeout=120))


@pytest.mark.parametrize("requetes", [2, 10])
async def test_deux_annulations_simultanees_ne_publient_qu_un_show_cancelled(
    requetes: int, client_admin: httpx.AsyncClient, catalogue: Any, base: Any
) -> None:
    evenement_id = str((await catalogue.evenement())["id"])
    lieu_id = str((await catalogue.lieu())["id"])
    for tour in range(1, TOURS + 1):
        seance_id = str(
            (await catalogue.seance(evenement_id, lieu_id, catalogue.instant(10 + tour)))["id"]
        )
        chemin = f"/api/v1/events/{evenement_id}/shows/{seance_id}/cancellation"

        reponses = await simultanees(requetes, lambda chemin=chemin: client_admin.post(chemin))

        statuts = Counter(r.status_code for r in reponses)
        assert statuts == {200: 1, 409: requetes - 1}, (
            f"tour {tour} : {dict(statuts)} : {[r.text for r in reponses[:3]]}"
        )
        codes = {r.json()["code"] for r in reponses if r.status_code == 409}
        assert codes <= {"SHOW_ALREADY_CANCELLED"}, f"tour {tour} : {codes}"
        publiees = [
            ligne
            for ligne in await base.lignes("SELECT * FROM outbox WHERE type = :t", t=TYPE)
            if ligne["data"].get("seance_id") == seance_id
        ]
        assert len(publiees) == 1, f"tour {tour} : {len(publiees)} show.cancelled"


LECTURES_DE_SEANCE = ("lireSeance", "lireSeanceParId", "listerSeances")


def _seance_lue(operation: str, corps: Any, seance_id: str) -> Any:
    if operation != "listerSeances":
        return corps
    trouvees = [element for element in corps["elements"] if element["id"] == seance_id]
    assert len(trouvees) == 1, f"S absente de listerSeances : {corps}"
    return trouvees[0]


@pytest.mark.parametrize("requetes", [2, 10])
async def test_des_annulations_et_lectures_simultanees_laissent_la_seance_lue_annulee(
    requetes: int, plateforme: Any, cache_redis: Any
) -> None:
    """Review BIL-011, point 6 : annulations simultanées sur un cache chaud, pendant que les
    trois lectures de la séance tournent ; une fois tout fini, aucune copie du cache ne rend
    la séance non annulée (invalidation par génération après le commit)."""
    for tour in range(1, TOURS + 1):
        chemins = await plateforme.semer_lectures()
        morceaux = chemins["lireSeance"].strip("/").split("/")
        evenement_id, seance_id = morceaux[3], morceaux[5]
        for operation in LECTURES_DE_SEANCE:
            avant = await plateforme.public.get(chemins[operation])
            assert avant.status_code == 200, f"tour {tour} : {avant.text}"
        await cache_redis.exiger_rempli(f"tour {tour}, cache chaud")
        chemin = f"/api/v1/events/{evenement_id}/shows/{seance_id}/cancellation"
        depart = asyncio.Event()

        async def annuler(chemin: str = chemin, depart: asyncio.Event = depart) -> httpx.Response:
            await depart.wait()
            return await plateforme.admin.post(chemin)  # type: ignore[no-any-return]

        async def lire(
            operation: str, chemins: dict[str, str] = chemins, depart: asyncio.Event = depart
        ) -> httpx.Response:
            await depart.wait()
            return await plateforme.public.get(chemins[operation])  # type: ignore[no-any-return]

        taches = [asyncio.create_task(annuler()) for _ in range(requetes)] + [
            asyncio.create_task(lire(operation)) for operation in LECTURES_DE_SEANCE * requetes
        ]
        await asyncio.sleep(0)
        depart.set()
        reponses = list(await asyncio.wait_for(asyncio.gather(*taches), timeout=120))

        annulations = reponses[:requetes]
        statuts = Counter(r.status_code for r in annulations)
        assert statuts == {200: 1, 409: requetes - 1}, f"tour {tour} : {dict(statuts)}"
        assert all(r.status_code == 200 for r in reponses[requetes:]), f"tour {tour}"
        for operation in LECTURES_DE_SEANCE:
            apres = await plateforme.public.get(chemins[operation])
            assert apres.status_code == 200, f"tour {tour} : {apres.text}"
            assert _seance_lue(operation, apres.json(), seance_id)["annulee"] is True, (
                f"tour {tour} : {operation} rend la séance non annulée"
            )
