"""Base injoignable : la dernière valeur en cache est servie avec X-Cache-Stale (CA2, E3, E6 ;
décisions D1, D2, D4, D7 ; questions Q7, Q10, Q11, Q17, Q18 du plan BIL-005)."""

from typing import Any
from uuid import uuid4

import httpx
import pytest

from catalogue.api.routes import EN_TETE_CACHE_PERIME

pytestmark = pytest.mark.anyio

LECTURES = [
    "listerEvenements",
    "lireEvenement",
    "listerSeances",
    "lireSeance",
    "lireSeanceParId",
    "listerLieux",
    "lireLieu",
]
ROUTE_EVENEMENTS = "/api/v1/events"
# Fraîcheur par défaut 30 s, secours 24 h (décision D7).
APRES_FRAICHEUR = 31.0
HEURE = 3600.0
VINGT_QUATRE_HEURES = 24 * HEURE


def _assert_base_indisponible(reponse: httpx.Response) -> None:
    assert reponse.status_code == 503, reponse.text
    assert reponse.headers["content-type"] == "application/problem+json"
    assert reponse.json()["code"] == "BASE_INDISPONIBLE"
    assert EN_TETE_CACHE_PERIME not in reponse.headers


def _assert_secours(reponse: httpx.Response) -> None:
    assert reponse.status_code == 200, reponse.text
    assert reponse.headers.get_list(EN_TETE_CACHE_PERIME) == ["true"]


# --- CA2 : base arrêtée, la lecture renvoie 200 depuis le cache -------------------------------


@pytest.mark.parametrize("operation", LECTURES)
async def test_chaque_lecture_deja_lue_renvoie_200_depuis_le_cache_quand_la_base_tombe(
    client: httpx.AsyncClient, depot: Any, cache: Any, semis: Any, operation: str
) -> None:
    chemin = semis.lectures[operation]
    premiere = await client.get(chemin)
    assert premiere.status_code == 200
    cache.avancer(APRES_FRAICHEUR)
    depot.injoignable = True

    reponse = await client.get(chemin)

    _assert_secours(reponse)
    assert reponse.content == premiere.content


@pytest.mark.parametrize("operation", LECTURES)
async def test_chaque_lecture_jamais_mise_en_cache_renvoie_503_quand_la_base_tombe(
    client: httpx.AsyncClient, depot: Any, semis: Any, operation: str
) -> None:
    depot.injoignable = True

    _assert_base_indisponible(await client.get(semis.lectures[operation]))


async def test_une_autre_page_que_celle_en_cache_renvoie_503_quand_la_base_tombe(
    client: httpx.AsyncClient, depot: Any, en_cache: Any
) -> None:
    depot.semer_evenement()
    await en_cache(f"{ROUTE_EVENEMENTS}?page=1")
    depot.injoignable = True

    _assert_base_indisponible(await client.get(f"{ROUTE_EVENEMENTS}?page=2"))


# --- E3 : en-tête qui signale la dernière valeur en cache (D1, D2, D4) ------------------------


async def test_une_reponse_de_secours_porte_x_cache_stale_true(
    client: httpx.AsyncClient, depot: Any, cache: Any, semis: Any
) -> None:
    chemin = semis.lectures["lireEvenement"]
    assert (await client.get(chemin)).status_code == 200
    cache.avancer(APRES_FRAICHEUR)
    depot.injoignable = True

    reponse = await client.get(chemin)

    assert reponse.status_code == 200, reponse.text
    # Présent une seule fois, valeur exacte « true ».
    assert reponse.headers.get_list(EN_TETE_CACHE_PERIME) == ["true"]


@pytest.mark.parametrize("operation", LECTURES)
async def test_une_lecture_depuis_la_base_ne_porte_pas_x_cache_stale(
    client: httpx.AsyncClient, semis: Any, operation: str
) -> None:
    reponse = await client.get(semis.lectures[operation])

    assert reponse.status_code == 200
    assert EN_TETE_CACHE_PERIME not in reponse.headers


@pytest.mark.parametrize("operation", LECTURES)
async def test_une_lecture_depuis_la_copie_fraiche_ne_porte_pas_x_cache_stale(
    client: httpx.AsyncClient, depot: Any, semis: Any, operation: str
) -> None:
    chemin = semis.lectures[operation]
    assert (await client.get(chemin)).status_code == 200
    avant = depot.lectures

    reponse = await client.get(chemin)

    assert reponse.status_code == 200
    assert depot.lectures == avant, "la seconde lecture n'est pas servie par la copie fraîche"
    assert EN_TETE_CACHE_PERIME not in reponse.headers


async def test_une_copie_fraiche_lue_pendant_une_panne_ne_porte_pas_x_cache_stale(
    client: httpx.AsyncClient, depot: Any, semis: Any
) -> None:
    chemin = semis.lectures["lireEvenement"]
    assert (await client.get(chemin)).status_code == 200
    depot.injoignable = True
    avant = depot.lectures

    reponse = await client.get(chemin)

    assert reponse.status_code == 200, reponse.text
    assert EN_TETE_CACHE_PERIME not in reponse.headers
    assert depot.lectures == avant


async def test_une_erreur_ne_porte_jamais_x_cache_stale(
    client: httpx.AsyncClient, depot: Any
) -> None:
    introuvable = await client.get(f"{ROUTE_EVENEMENTS}/{uuid4()}")
    invalide = await client.get(f"{ROUTE_EVENEMENTS}?size=0")
    depot.injoignable = True
    indisponible = await client.get(ROUTE_EVENEMENTS)

    assert introuvable.status_code == 404
    assert invalide.status_code == 422
    assert indisponible.status_code == 503
    for reponse in (introuvable, invalide, indisponible):
        assert EN_TETE_CACHE_PERIME not in reponse.headers


async def test_aucune_reponse_ne_porte_d_en_tete_age(
    client: httpx.AsyncClient, depot: Any, cache: Any, semis: Any
) -> None:
    chemin = semis.lectures["lireEvenement"]
    introuvable = await client.get(f"{ROUTE_EVENEMENTS}/{uuid4()}")
    depuis_la_base = await client.get(chemin)
    depuis_la_copie_fraiche = await client.get(chemin)
    cache.avancer(APRES_FRAICHEUR)
    depot.injoignable = True
    depuis_le_secours = await client.get(chemin)
    indisponible = await client.get(f"/api/v1/venues/{uuid4()}")

    assert introuvable.status_code == 404
    assert depuis_la_base.status_code == 200
    assert depuis_la_copie_fraiche.status_code == 200
    _assert_secours(depuis_le_secours)
    assert indisponible.status_code == 503
    for reponse in (
        depuis_la_base,
        depuis_la_copie_fraiche,
        depuis_le_secours,
        introuvable,
        indisponible,
    ):
        assert "age" not in reponse.headers


async def test_une_erreur_de_base_autre_qu_injoignable_ne_sert_pas_le_secours(
    client: httpx.AsyncClient, depot: Any, cache: Any, en_cache: Any
) -> None:
    depot.semer_evenement()
    await en_cache(ROUTE_EVENEMENTS)
    cache.avancer(APRES_FRAICHEUR)
    depot.erreur_imprevue = True

    reponse = await client.get(ROUTE_EVENEMENTS)

    assert reponse.status_code == 500, reponse.text
    assert reponse.json()["code"] == "ERREUR_INTERNE"
    assert EN_TETE_CACHE_PERIME not in reponse.headers


# --- E6 : copie de secours de 24 h, lue seulement si la base ne répond pas (D7) ---------------


async def test_la_copie_de_secours_n_est_pas_lue_quand_la_base_repond(
    client: httpx.AsyncClient, depot: Any, cache: Any, semis: Any
) -> None:
    chemin = semis.lectures["lireEvenement"]
    assert (await client.get(chemin)).status_code == 200
    depot.renommer_evenement(semis.evenement.id, "Nom modifié")
    cache.avancer(APRES_FRAICHEUR)

    reponse = await client.get(chemin)

    assert reponse.status_code == 200
    assert reponse.json()["nom"] == "Nom modifié"
    assert EN_TETE_CACHE_PERIME not in reponse.headers


async def test_la_copie_de_secours_sert_jusqu_a_24_heures(
    client: httpx.AsyncClient, depot: Any, cache: Any, semis: Any
) -> None:
    chemin = semis.lectures["lireEvenement"]
    assert (await client.get(chemin)).status_code == 200
    cache.avancer(23 * HEURE + 59 * 60)
    depot.injoignable = True

    _assert_secours(await client.get(chemin))


async def test_la_copie_de_secours_expire_apres_24_heures(
    client: httpx.AsyncClient, depot: Any, cache: Any, semis: Any
) -> None:
    chemin = semis.lectures["lireEvenement"]
    assert (await client.get(chemin)).status_code == 200
    cache.avancer(VINGT_QUATRE_HEURES + 1)
    depot.injoignable = True

    _assert_base_indisponible(await client.get(chemin))


async def test_chaque_lecture_reussie_en_base_repousse_l_expiration_du_secours(
    client: httpx.AsyncClient, depot: Any, cache: Any, semis: Any
) -> None:
    chemin = semis.lectures["lireEvenement"]
    assert (await client.get(chemin)).status_code == 200
    cache.avancer(20 * HEURE)
    relecture = await client.get(chemin)
    assert relecture.status_code == 200
    cache.avancer(10 * HEURE)
    depot.injoignable = True

    _assert_secours(await client.get(chemin))


@pytest.mark.parametrize("operation", LECTURES)
async def test_la_copie_de_secours_garde_le_corps_exact_de_la_base(
    client: httpx.AsyncClient, depot: Any, cache: Any, semis: Any, operation: str
) -> None:
    chemin = semis.lectures[operation]
    depuis_la_base = await client.get(chemin)
    assert depuis_la_base.status_code == 200
    cache.avancer(APRES_FRAICHEUR)
    depot.injoignable = True

    depuis_le_secours = await client.get(chemin)

    _assert_secours(depuis_le_secours)
    # Octet pour octet, dates avec fuseau comprises (Q11).
    assert depuis_le_secours.content == depuis_la_base.content
    assert depuis_le_secours.headers["content-type"] == "application/json"
