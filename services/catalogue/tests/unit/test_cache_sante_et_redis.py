"""`/health` ignore le cache (E4, D3) ; Redis injoignable, le catalogue reste disponible (E9 ;
questions Q3, Q5, Q6 du plan BIL-005).

Les cas de santé démarrent la vraie application (lifespan) : base SQLite en mémoire quand elle
doit répondre, URL PostgreSQL sur le port 1 (fermé) quand elle doit être injoignable.
"""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio
import httpx
import pytest
from fastapi import FastAPI

from catalogue.api.dependances import obtenir_cache
from catalogue.api.routes import EN_TETE_CACHE_PERIME
from catalogue.config import Parametres
from catalogue.principal import creer_app
from commun.faux_jetons import EmetteurDeTest

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
URL_SQLITE = "sqlite+aiosqlite://"
URL_FERMEE = f"postgresql+asyncpg://catalogue:{secrets.token_urlsafe(16)}@127.0.0.1:1/catalogue"


@asynccontextmanager
async def _application_demarree(
    emetteur: EmetteurDeTest, database_url: str, cache: Any
) -> AsyncIterator[httpx.AsyncClient]:
    config = Parametres(database_url=database_url, instance="catalogue-test", consul_actif=False)
    app: FastAPI = creer_app(config, verificateur_jetons=emetteur.verificateur())
    app.dependency_overrides[obtenir_cache] = lambda: cache
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        yield client


# --- E4 : /health exclu du cache (D3) ---------------------------------------------------------


async def test_la_sante_repond_503_quand_la_base_tombe_meme_avec_un_cache_rempli(
    client: httpx.AsyncClient, cache: Any, semis: Any, emetteur: EmetteurDeTest
) -> None:
    async with _application_demarree(emetteur, URL_SQLITE, cache) as disponible:
        assert (await disponible.get("/health")).status_code == 200
    for chemin in semis.lectures.values():
        assert (await client.get(chemin)).status_code == 200
    assert len(cache.valeurs()) >= len(semis.lectures), "les 7 lectures ne sont pas en cache"

    async with _application_demarree(emetteur, URL_FERMEE, cache) as sans_base:
        reponse = await sans_base.get("/health")

    assert reponse.status_code == 503, reponse.text
    assert reponse.headers["content-type"] == "application/problem+json"
    assert reponse.json()["code"] == "BASE_INDISPONIBLE"
    assert EN_TETE_CACHE_PERIME not in reponse.headers


async def test_la_sante_repond_200_quand_redis_est_injoignable(
    cache: Any, emetteur: EmetteurDeTest
) -> None:
    cache.injoignable = True

    async with _application_demarree(emetteur, URL_SQLITE, cache) as disponible:
        reponse = await disponible.get("/health")

    assert reponse.status_code == 200, reponse.text
    assert reponse.json() == {"statut": "ok"}


# --- E9 : Redis injoignable, le catalogue reste disponible ------------------------------------


async def test_sans_redis_url_le_service_lit_la_base_sans_cache(
    anonyme: httpx.AsyncClient, depot: Any, semis: Any
) -> None:
    chemin = semis.lectures["lireEvenement"]
    premiere = await anonyme.get(chemin)
    depot.renommer_evenement(semis.evenement.id, "Nom modifié")

    seconde = await anonyme.get(chemin)

    assert premiere.status_code == 200
    assert seconde.status_code == 200
    assert seconde.json()["nom"] == "Nom modifié"


def _attendu(semis: Any, operation: str) -> str | None:
    """Identifiant attendu dans le corps d'un détail ; None pour une liste."""
    return {
        "lireEvenement": str(semis.evenement.id),
        "lireSeance": str(semis.seance.id),
        "lireSeanceParId": str(semis.seance.id),
        "lireLieu": str(semis.lieu.id),
    }.get(operation)


@pytest.mark.parametrize("operation", LECTURES)
async def test_redis_injoignable_la_lecture_repond_200_depuis_la_base_sans_en_tete(
    client: httpx.AsyncClient, cache: Any, semis: Any, operation: str
) -> None:
    cache.injoignable = True

    reponse = await client.get(semis.lectures[operation])

    assert reponse.status_code == 200, reponse.text
    assert EN_TETE_CACHE_PERIME not in reponse.headers
    attendu = _attendu(semis, operation)
    if attendu is None:
        assert reponse.json()["total"] == 1
    else:
        assert reponse.json()["id"] == attendu


async def test_redis_qui_ne_repond_pas_ne_retient_pas_la_lecture_au_dela_du_delai(
    fabrique_app: Any, cache: Any, semis: Any
) -> None:
    cache.lent = True
    app = fabrique_app(cache, delai_redis=0.2)
    transport = httpx.ASGITransport(app=app)
    reponse: httpx.Response | None = None

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with anyio.move_on_after(2) as portee:
            reponse = await client.get(semis.lectures["lireEvenement"])

    assert not portee.cancelled_caught, "lecture retenue plus de 2 s par Redis"
    assert reponse is not None
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["id"] == str(semis.evenement.id)


async def test_redis_injoignable_une_creation_admin_repond_201(
    client: httpx.AsyncClient,
    depot: Any,
    cache: Any,
    semis: Any,
    entetes_admin: dict[str, str],
    evenement_valide: dict[str, str],
    lieu_valide: dict[str, str],
    seance_valide: Any,
) -> None:
    cache.injoignable = True

    evenement = await client.post("/api/v1/events", json=evenement_valide, headers=entetes_admin)
    lieu = await client.post("/api/v1/venues", json=lieu_valide, headers=entetes_admin)
    seance = await client.post(
        semis.lectures["listerSeances"], json=seance_valide(semis.lieu.id), headers=entetes_admin
    )

    assert evenement.status_code == 201, evenement.text
    assert lieu.status_code == 201, lieu.text
    assert seance.status_code == 201, seance.text
    assert any(str(e) == evenement.json()["id"] for e in depot.evenements)
    assert any(str(lieu_id) == lieu.json()["id"] for lieu_id in depot.lieux)
    assert any(str(s) == seance.json()["id"] for s in depot.seances)


async def test_redis_injoignable_et_base_injoignable_la_lecture_repond_503(
    client: httpx.AsyncClient, depot: Any, cache: Any, semis: Any
) -> None:
    cache.injoignable = True
    depot.injoignable = True

    reponse = await client.get(semis.lectures["listerEvenements"])

    assert reponse.status_code == 503, reponse.text
    assert reponse.json()["code"] == "BASE_INDISPONIBLE"
    assert EN_TETE_CACHE_PERIME not in reponse.headers
