"""E2 (BIL-005, D8, Q12, Q13, Q15) : chaque création admin invalide sa famille de listes.

« La copie de secours a disparu » se vérifie de l'extérieur : base en pause, la même lecture
répond 503 au lieu de 200 `X-Cache-Stale: true`. Un témoin vérifie d'abord que le cache a
gardé une copie (clé `catalogue:cache:*`) : sans cache actif, le 503 ne prouverait rien.
"""

from typing import Any

import anyio
import httpx
import pytest

from catalogue.api.routes import EN_TETE_CACHE_PERIME

pytestmark = pytest.mark.anyio


def _assert_base_indisponible(reponse: httpx.Response) -> None:
    assert reponse.status_code == 503, reponse.text
    assert reponse.headers["content-type"].startswith("application/problem+json")
    assert reponse.json()["code"] == "BASE_INDISPONIBLE"
    assert EN_TETE_CACHE_PERIME not in reponse.headers


def _assert_secours(reponse: httpx.Response) -> None:
    assert reponse.status_code == 200, reponse.text
    assert reponse.headers.get_list(EN_TETE_CACHE_PERIME) == ["true"]


async def _famille_evenements(p: Any) -> tuple[list[tuple[str, dict[str, Any]]], Any]:
    await p.catalogue.evenement()

    async def creer() -> None:
        await p.catalogue.evenement(nom="Concert ajouté")

    return [("/api/v1/events", {"size": 1})], creer


async def _famille_lieux(p: Any) -> tuple[list[tuple[str, dict[str, Any]]], Any]:
    await p.catalogue.lieu()

    async def creer() -> None:
        await p.catalogue.lieu(nom="Salle ajoutée")

    return [("/api/v1/venues", {})], creer


async def _famille_seances(p: Any) -> tuple[list[tuple[str, dict[str, Any]]], Any]:
    evenement = str((await p.catalogue.evenement())["id"])
    lieu = str((await p.catalogue.lieu())["id"])
    await p.catalogue.seance(evenement, lieu)

    async def creer() -> None:
        await p.catalogue.seance(evenement, lieu, debut=p.catalogue.instant(31))

    lectures = [
        (f"/api/v1/events/{evenement}/shows", {}),
        ("/api/v1/events", {"ville": "Villetest"}),
    ]
    return lectures, creer


FAMILLES = {
    "creerEvenement": _famille_evenements,
    "creerLieu": _famille_lieux,
    "creerSeance": _famille_seances,
}


@pytest.mark.parametrize("ecriture", list(FAMILLES))
async def test_apres_chaque_creation_la_famille_n_a_plus_de_copie_de_secours(
    ecriture: str,
    plateforme: Any,
    cache_redis: Any,
    postgres: Any,
    en_pause: Any,
    borner: Any,
) -> None:
    lectures, creer = await FAMILLES[ecriture](plateforme)
    await cache_redis.vider()
    for chemin, params in lectures:
        lecture = await plateforme.public.get(chemin, params=params)
        assert lecture.status_code == 200, f"GET {chemin} {params} : {lecture.text}"
    await cache_redis.exiger_rempli(f"après les lectures de la famille de {ecriture}")

    await creer()
    with en_pause(postgres):
        pendant = [
            await borner(
                f"GET {chemin} {params}, base en pause",
                plateforme.public.get(chemin, params=params),
                plateforme.delai_lecture,
            )
            for chemin, params in lectures
        ]

    for reponse in pendant:
        _assert_base_indisponible(reponse)


async def test_une_creation_ne_vide_pas_le_cache_des_autres_familles(
    plateforme: Any,
    cache_redis: Any,
    postgres: Any,
    en_pause: Any,
    borner: Any,
    attente_fraicheur: float,
) -> None:
    lieu = await plateforme.catalogue.lieu()
    evenement = await plateforme.catalogue.evenement()
    chemins = [f"/api/v1/venues/{lieu['id']}", f"/api/v1/events/{evenement['id']}"]
    await cache_redis.vider()
    for chemin in chemins:
        assert (await plateforme.public.get(chemin)).status_code == 200, chemin

    await plateforme.catalogue.evenement(nom="Concert ajouté")
    await anyio.sleep(attente_fraicheur)
    with en_pause(postgres):
        pendant = [
            await borner(
                f"GET {chemin}, base en pause",
                plateforme.public.get(chemin),
                plateforme.delai_lecture,
            )
            for chemin in chemins
        ]

    for reponse in pendant:
        _assert_secours(reponse)


async def test_une_creation_en_503_pendant_la_pause_garde_la_copie_de_secours(
    plateforme: Any,
    cache_redis: Any,
    postgres: Any,
    en_pause: Any,
    borner: Any,
    attente_fraicheur: float,
) -> None:
    await plateforme.catalogue.evenement()
    await cache_redis.vider()
    assert (await plateforme.public.get("/api/v1/events")).status_code == 200
    await anyio.sleep(attente_fraicheur)

    with en_pause(postgres):
        creation = await borner(
            "POST /api/v1/events, base en pause",
            plateforme.admin.post("/api/v1/events", json=plateforme.catalogue.EVENEMENT),
            plateforme.delai_lecture,
        )
        lecture = await borner(
            "GET /api/v1/events, base en pause",
            plateforme.public.get("/api/v1/events"),
            plateforme.delai_lecture,
        )

    _assert_base_indisponible(creation)
    _assert_secours(lecture)
