"""CA1 (BIL-005) : une modification admin est visible immédiatement, malgré le cache Redis.

Vraie base migrée, vrai Redis. Chaque cas vérifie d'abord, par un témoin, que le cache a gardé
une copie (clé `catalogue:cache:*`) : sans cache actif, la visibilité serait triviale. Redis est
vidé après la mise en place des données, pour que seules les lectures du cas le remplissent.
"""

from typing import Any

import anyio
import httpx
import pytest

from catalogue.api.routes import EN_TETE_CACHE_PERIME
from catalogue.config import DELAI_BASE_PAR_DEFAUT, DUREE_FRAICHE_PAR_DEFAUT

pytestmark = pytest.mark.anyio

TOURS_SIMULTANES = 10
LECTURES_PAR_TOUR = 50


def _ids(reponse: httpx.Response) -> list[str]:
    assert reponse.status_code == 200, reponse.text
    return [element["id"] for element in reponse.json()["elements"]]


async def _lire_deux_fois(client: httpx.AsyncClient, chemin: str, **options: Any) -> None:
    for _ in range(2):
        reponse = await client.get(chemin, **options)
        assert reponse.status_code == 200, f"GET {chemin} : {reponse.text}"


async def test_un_evenement_cree_par_l_api_est_visible_a_la_relecture_immediate_malgre_le_cache(
    plateforme_cache: Any, cache_redis: Any
) -> None:
    async with plateforme_cache(cache_duree_fraiche=DUREE_FRAICHE_PAR_DEFAUT) as p:
        await p.catalogue.evenement()
        await cache_redis.vider()
        await _lire_deux_fois(p.public, "/api/v1/events")
        await cache_redis.exiger_rempli("après deux GET /api/v1/events")

        nouveau = await p.catalogue.evenement(nom="Concert ajouté")
        relecture = await p.public.get("/api/v1/events")

    assert nouveau["id"] in _ids(relecture)
    assert relecture.json()["total"] == 2
    assert EN_TETE_CACHE_PERIME not in relecture.headers


async def test_un_lieu_cree_par_l_api_est_visible_a_la_relecture_immediate_malgre_le_cache(
    plateforme_cache: Any, cache_redis: Any
) -> None:
    async with plateforme_cache(cache_duree_fraiche=DUREE_FRAICHE_PAR_DEFAUT) as p:
        await p.catalogue.lieu()
        await cache_redis.vider()
        await _lire_deux_fois(p.public, "/api/v1/venues")
        await cache_redis.exiger_rempli("après deux GET /api/v1/venues")

        nouveau = await p.catalogue.lieu(nom="Salle ajoutée")
        relecture = await p.public.get("/api/v1/venues")

    assert nouveau["id"] in _ids(relecture)
    assert relecture.json()["total"] == 2
    assert EN_TETE_CACHE_PERIME not in relecture.headers


async def test_une_seance_programmee_par_l_api_est_visible_a_la_relecture_immediate_malgre_le_cache(
    plateforme_cache: Any, cache_redis: Any
) -> None:
    async with plateforme_cache(cache_duree_fraiche=DUREE_FRAICHE_PAR_DEFAUT) as p:
        evenement = str((await p.catalogue.evenement())["id"])
        villetest = str((await p.catalogue.lieu())["id"])
        autreville = str((await p.catalogue.lieu(ville="Autreville"))["id"])
        # Première séance à Autreville : la recherche par ville « Villetest » ne retient pas E.
        await p.catalogue.seance(evenement, autreville)
        await cache_redis.vider()
        seances = f"/api/v1/events/{evenement}/shows"
        par_ville = {"params": {"ville": "Villetest"}}
        await _lire_deux_fois(p.public, seances)
        await _lire_deux_fois(p.public, "/api/v1/events", **par_ville)
        await cache_redis.exiger_rempli("après les lectures des séances et de ?ville=Villetest")

        nouvelle = await p.catalogue.seance(evenement, villetest)
        relecture_seances = await p.public.get(seances)
        relecture_ville = await p.public.get("/api/v1/events", **par_ville)

    assert nouvelle["id"] in _ids(relecture_seances)
    assert relecture_seances.json()["total"] == 2
    assert evenement in _ids(relecture_ville)
    assert relecture_ville.json()["total"] == 1


async def test_une_creation_est_visible_sur_toutes_les_pages_et_tous_les_filtres_deja_en_cache(
    plateforme_cache: Any, cache_redis: Any
) -> None:
    lectures: dict[str, dict[str, Any]] = {
        "page 1 (size 2)": {"page": 1, "size": 2},
        "page 2 (size 2)": {"page": 2, "size": 2},
        "q=Concert": {"q": "Concert"},
        "sans paramètre": {},
    }
    async with plateforme_cache(cache_duree_fraiche=DUREE_FRAICHE_PAR_DEFAUT) as p:
        for _ in range(3):
            await p.catalogue.evenement()
        await cache_redis.vider()
        for params in lectures.values():
            await _lire_deux_fois(p.public, "/api/v1/events", params=params)
        await cache_redis.exiger_rempli("après les quatre lectures de /api/v1/events")

        quatrieme = await p.catalogue.evenement()
        relectures = {
            nom: await p.public.get("/api/v1/events", params=params)
            for nom, params in lectures.items()
        }

    totaux = {nom: reponse.json().get("total") for nom, reponse in relectures.items()}
    assert totaux == dict.fromkeys(lectures, 4)
    assert quatrieme["id"] in _ids(relectures["page 2 (size 2)"])


async def test_des_lectures_simultanees_pendant_une_creation_ne_laissent_pas_l_ancienne_liste_en_cache(  # noqa: E501
    plateforme_cache: Any, cache_redis: Any
) -> None:
    # delai_base par défaut : 50 lectures simultanées attendent leur tour dans le pool.
    async with plateforme_cache(
        cache_duree_fraiche=DUREE_FRAICHE_PAR_DEFAUT, delai_base=DELAI_BASE_PAR_DEFAUT
    ) as p:
        await p.catalogue.evenement()
        await cache_redis.vider()
        await _lire_deux_fois(p.public, "/api/v1/events")
        await cache_redis.exiger_rempli("après deux GET /api/v1/events")

        tours_fautifs: list[int] = []
        for tour in range(TOURS_SIMULTANES):
            crees: list[dict[str, Any]] = []

            async def lire() -> None:
                await p.public.get("/api/v1/events")

            async def creer(numero: int = tour, crees: list[dict[str, Any]] = crees) -> None:
                crees.append(await p.catalogue.evenement(nom=f"Concert du tour {numero}"))

            async with anyio.create_task_group() as groupe:
                for _ in range(LECTURES_PAR_TOUR // 2):
                    groupe.start_soon(lire)
                groupe.start_soon(creer)
                for _ in range(LECTURES_PAR_TOUR - LECTURES_PAR_TOUR // 2):
                    groupe.start_soon(lire)

            apres = await p.public.get("/api/v1/events")
            if crees[0]["id"] not in _ids(apres):
                tours_fautifs.append(tour)

    assert tours_fautifs == [], (
        f"ancienne liste restée en cache après les tours {tours_fautifs} (sur {TOURS_SIMULTANES})"
    )
