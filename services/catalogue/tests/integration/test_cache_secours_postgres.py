"""CA2, E4, E5, E6, E8 (BIL-005) : base en pause, la lecture déjà lue répond depuis le cache.

Le conteneur PostgreSQL du module est mis en pause (`docker pause`) pendant que le service
tourne. Durées de test : fraîcheur 1 s, delai_base 1 s ; chaque lecture pendant la pause est
bornée à delai_base + 5 s (Q8). Les cas qui attendent un 503 vérifient d'abord, par un témoin,
que le cache a gardé une copie (clé `catalogue:cache:*`).
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import anyio
import httpx
import pytest
import yaml
from jsonschema import Draft202012Validator

from catalogue.api.routes import EN_TETE_CACHE_PERIME

pytestmark = pytest.mark.anyio

CONTRAT = Path(__file__).resolve().parents[2] / "openapi.yaml"
OPERATIONS_DE_LECTURE = (
    "listerEvenements",
    "lireEvenement",
    "listerSeances",
    "lireSeance",
    "lireSeanceParId",
    "listerLieux",
    "lireLieu",
)
CHAMPS_DATE = {"cree_le", "debut"}


def _assert_base_indisponible(reponse: httpx.Response) -> None:
    assert reponse.status_code == 503, reponse.text
    assert reponse.headers["content-type"].startswith("application/problem+json")
    assert reponse.json()["code"] == "BASE_INDISPONIBLE"
    assert EN_TETE_CACHE_PERIME not in reponse.headers


def _assert_secours(reponse: httpx.Response) -> None:
    assert reponse.status_code == 200, reponse.text
    assert reponse.headers.get_list(EN_TETE_CACHE_PERIME) == ["true"]


def _operation(contrat: dict[str, Any], operation_id: str) -> dict[str, Any]:
    for operations in contrat["paths"].values():
        for definition in operations.values():
            if isinstance(definition, dict) and definition.get("operationId") == operation_id:
                return definition
    raise AssertionError(f"{operation_id} absent du contrat")


def _dates_sans_fuseau(valeur: Any, chemin: str = "$") -> list[str]:
    fautifs: list[str] = []
    if isinstance(valeur, dict):
        for cle, sous_valeur in valeur.items():
            if cle in CHAMPS_DATE and datetime.fromisoformat(sous_valeur).tzinfo is None:
                fautifs.append(f"{chemin}.{cle}")
            fautifs += _dates_sans_fuseau(sous_valeur, f"{chemin}.{cle}")
    elif isinstance(valeur, list):
        for indice, element in enumerate(valeur):
            fautifs += _dates_sans_fuseau(element, f"{chemin}[{indice}]")
    return fautifs


@pytest.fixture(scope="module")
def contrat() -> dict[str, Any]:
    return yaml.safe_load(CONTRAT.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


# --- CA2 ------------------------------------------------------------------------------------


@pytest.mark.parametrize("operation", OPERATIONS_DE_LECTURE)
async def test_chaque_lecture_deja_lue_renvoie_200_depuis_le_cache_pendant_la_pause_de_la_base(
    operation: str,
    plateforme: Any,
    postgres: Any,
    en_pause: Any,
    borner: Any,
    attente_fraicheur: float,
) -> None:
    chemin = (await plateforme.semer_lectures())[operation]
    premiere = await plateforme.public.get(chemin)
    assert premiere.status_code == 200, premiere.text
    await anyio.sleep(attente_fraicheur)

    with en_pause(postgres):
        debut = time.monotonic()
        pendant = await borner(
            f"GET {chemin}, base en pause",
            plateforme.public.get(chemin),
            plateforme.delai_lecture,
        )
        duree = time.monotonic() - debut

    _assert_secours(pendant)
    assert pendant.content == premiere.content
    assert duree < plateforme.delai_lecture


async def test_une_lecture_jamais_lue_renvoie_503_pendant_la_pause_de_la_base(
    plateforme: Any, cache_redis: Any, postgres: Any, en_pause: Any, borner: Any
) -> None:
    await plateforme.catalogue.lieu()
    await cache_redis.vider()
    assert (await plateforme.public.get("/api/v1/venues")).status_code == 200
    await cache_redis.exiger_rempli("après GET /api/v1/venues (page 1)")

    with en_pause(postgres):
        detail = await borner(
            "GET /api/v1/venues/{inconnu}, base en pause",
            plateforme.public.get(f"/api/v1/venues/{uuid4()}"),
            plateforme.delai_lecture,
        )
        page_3 = await borner(
            "GET /api/v1/venues?page=3, base en pause",
            plateforme.public.get("/api/v1/venues", params={"page": 3}),
            plateforme.delai_lecture,
        )

    _assert_base_indisponible(detail)
    _assert_base_indisponible(page_3)


async def test_au_retour_de_la_base_la_lecture_repond_200_sans_x_cache_stale(
    plateforme: Any,
    base: Any,
    postgres: Any,
    en_pause: Any,
    borner: Any,
    attente_fraicheur: float,
) -> None:
    lieu = await plateforme.catalogue.lieu()
    chemin = f"/api/v1/venues/{lieu['id']}"
    assert (await plateforme.public.get(chemin)).status_code == 200
    await base.executer(
        "UPDATE lieux SET nom = :nom WHERE id = :id", nom="Nom modifié", id=UUID(lieu["id"])
    )
    await anyio.sleep(attente_fraicheur)

    with en_pause(postgres):
        pendant = await borner(
            f"GET {chemin}, base en pause", plateforme.public.get(chemin), plateforme.delai_lecture
        )
    apres = await borner(f"GET {chemin}, base reprise", plateforme.public.get(chemin))

    _assert_secours(pendant)
    assert pendant.json()["nom"] == lieu["nom"]
    assert apres.status_code == 200, apres.text
    assert EN_TETE_CACHE_PERIME not in apres.headers
    assert apres.json()["nom"] == "Nom modifié"


async def test_base_et_redis_en_pause_une_lecture_renvoie_503(
    plateforme: Any,
    cache_redis: Any,
    postgres: Any,
    redis: Any,
    en_pause: Any,
    borner: Any,
    attente_fraicheur: float,
) -> None:
    evenement = await plateforme.catalogue.evenement()
    chemin = f"/api/v1/events/{evenement['id']}"
    await cache_redis.vider()
    assert (await plateforme.public.get(chemin)).status_code == 200
    await cache_redis.exiger_rempli(f"après GET {chemin}")
    await anyio.sleep(attente_fraicheur)

    with en_pause(postgres, redis):
        pendant = await borner(
            f"GET {chemin}, base et Redis en pause",
            plateforme.public.get(chemin),
            plateforme.delai_lecture,
        )

    _assert_base_indisponible(pendant)


# --- E4 : /health exclu du cache ------------------------------------------------------------


async def test_la_sante_repond_503_pendant_la_pause_de_la_base_malgre_le_cache(
    plateforme: Any, cache_redis: Any, postgres: Any, en_pause: Any, borner: Any
) -> None:
    chemins = await plateforme.semer_lectures()
    await cache_redis.vider()
    for chemin in chemins.values():
        assert (await plateforme.public.get(chemin)).status_code == 200, chemin
    await cache_redis.exiger_rempli("après les 7 lectures")

    with en_pause(postgres):
        sante = await borner(
            "GET /health, base en pause",
            plateforme.public.get("/health"),
            plateforme.delai_lecture,
        )

    _assert_base_indisponible(sante)


# --- E5 : un 404 n'est jamais servi depuis le cache -----------------------------------------


async def test_un_identifiant_inconnu_renvoie_503_et_non_404_pendant_la_pause_de_la_base(
    plateforme: Any,
    cache_redis: Any,
    postgres: Any,
    en_pause: Any,
    borner: Any,
    attente_fraicheur: float,
) -> None:
    await plateforme.catalogue.lieu()
    await cache_redis.vider()
    assert (await plateforme.public.get("/api/v1/venues")).status_code == 200
    await cache_redis.exiger_rempli("après GET /api/v1/venues")
    chemin = f"/api/v1/venues/{uuid4()}"
    avant = await plateforme.public.get(chemin)
    assert avant.status_code == 404, avant.text
    await anyio.sleep(attente_fraicheur)

    with en_pause(postgres):
        pendant = await borner(
            f"GET {chemin}, base en pause", plateforme.public.get(chemin), plateforme.delai_lecture
        )

    _assert_base_indisponible(pendant)


# --- E6 : copie de secours, durée configurée ------------------------------------------------


async def test_la_copie_de_secours_expire_apres_la_duree_configuree(
    plateforme_cache: Any, postgres: Any, en_pause: Any, borner: Any, attente_fraicheur: float
) -> None:
    duree_secours = 5.0
    async with plateforme_cache(cache_duree_secours=duree_secours) as p:
        evenement = await p.catalogue.evenement()
        chemin = f"/api/v1/events/{evenement['id']}"
        assert (await p.public.get(chemin)).status_code == 200
        lu_le = time.monotonic()
        await anyio.sleep(attente_fraicheur)

        # Témoin : avant l'échéance, la copie de secours sert la lecture.
        with en_pause(postgres):
            avant_echeance = await borner(
                f"GET {chemin}, base en pause avant l'échéance",
                p.public.get(chemin),
                p.delai_lecture,
            )
        _assert_secours(avant_echeance)

        await anyio.sleep(max(0.0, lu_le + duree_secours + 1.5 - time.monotonic()))
        with en_pause(postgres):
            apres_echeance = await borner(
                f"GET {chemin}, base en pause après l'échéance",
                p.public.get(chemin),
                p.delai_lecture,
            )

    _assert_base_indisponible(apres_echeance)


# --- E8 : réponse de secours conforme au contrat --------------------------------------------


@pytest.mark.parametrize("operation", OPERATIONS_DE_LECTURE)
async def test_chaque_reponse_de_secours_respecte_le_schema_et_l_en_tete_du_contrat(
    operation: str,
    contrat: dict[str, Any],
    plateforme: Any,
    postgres: Any,
    en_pause: Any,
    borner: Any,
    attente_fraicheur: float,
) -> None:
    reponse_200 = _operation(contrat, operation)["responses"]["200"]
    schema = reponse_200["content"]["application/json"]["schema"]
    valeurs_en_tete = reponse_200["headers"][EN_TETE_CACHE_PERIME]["schema"]["enum"]
    chemin = (await plateforme.semer_lectures())[operation]
    assert (await plateforme.public.get(chemin)).status_code == 200
    await anyio.sleep(attente_fraicheur)

    with en_pause(postgres):
        pendant = await borner(
            f"GET {chemin}, base en pause", plateforme.public.get(chemin), plateforme.delai_lecture
        )

    assert pendant.status_code == 200, pendant.text
    assert pendant.headers["content-type"].startswith("application/json")
    assert pendant.headers.get(EN_TETE_CACHE_PERIME) in valeurs_en_tete
    corps = pendant.json()
    validateur = Draft202012Validator({**schema, "components": contrat["components"]})
    erreurs = [f"{list(e.absolute_path)} : {e.message}" for e in validateur.iter_errors(corps)]
    assert erreurs == [], erreurs
    assert _dates_sans_fuseau(corps) == []
