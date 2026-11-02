"""Cache-aside des lectures, durée de vie courte (E1, D7), seuls les 200 en cache (E5, D5),
aucune disponibilité des places en cache (E7, D9) ; questions Q4, Q10, Q11, Q19 du plan
BIL-005."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import yaml
from pydantic import ValidationError

from catalogue.config import Parametres

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
URL_BASE = "postgresql+asyncpg://test@localhost/catalogue"
VARIABLES_DUREES = ("CACHE_DUREE_FRAICHE", "CACHE_DUREE_SECOURS")
APRES_FRAICHEUR = 31.0
CONTRAT_SERVICE = Path(__file__).resolve().parents[2] / "openapi.yaml"


def _assert_base_indisponible(reponse: httpx.Response) -> None:
    assert reponse.status_code == 503, reponse.text
    assert reponse.json()["code"] == "BASE_INDISPONIBLE"


# --- E1 : cache-aside, fraîcheur 30 s (D7) ----------------------------------------------------


@pytest.mark.parametrize("operation", LECTURES)
async def test_une_seconde_lecture_dans_les_30_secondes_ne_relit_pas_la_base(
    client: httpx.AsyncClient, depot: Any, cache: Any, semis: Any, operation: str
) -> None:
    chemin = semis.lectures[operation]
    premiere = await client.get(chemin)
    assert premiere.status_code == 200
    avant = depot.lectures
    cache.avancer(29)

    seconde = await client.get(chemin)

    assert seconde.status_code == 200
    assert depot.lectures == avant
    assert seconde.content == premiere.content


async def test_apres_30_secondes_la_lecture_relit_la_base(
    client: httpx.AsyncClient, depot: Any, cache: Any, semis: Any
) -> None:
    chemin = semis.lectures["lireEvenement"]
    assert (await client.get(chemin)).status_code == 200
    depot.renommer_evenement(semis.evenement.id, "Nom modifié")
    cache.avancer(APRES_FRAICHEUR)
    avant = depot.lectures

    reponse = await client.get(chemin)

    assert reponse.json()["nom"] == "Nom modifié"
    assert depot.lectures == avant + 1


async def test_deux_requetes_aux_parametres_equivalents_partagent_la_meme_entree(
    client: httpx.AsyncClient, depot: Any
) -> None:
    depot.semer_evenement()
    assert (await client.get(ROUTE_EVENEMENTS)).status_code == 200
    avant = depot.lectures

    reponse = await client.get(f"{ROUTE_EVENEMENTS}?page=1&size=20")

    assert reponse.status_code == 200
    assert depot.lectures == avant


async def test_deux_filtres_differents_ne_partagent_pas_la_meme_entree(
    client: httpx.AsyncClient, depot: Any, semis: Any
) -> None:
    for filtre in ("q=Concert", "q=concert", "ville=Villetest"):
        avant = depot.lectures

        reponse = await client.get(f"{ROUTE_EVENEMENTS}?{filtre}")

        assert reponse.status_code == 200
        assert depot.lectures > avant, f"?{filtre} servi par l'entrée d'un autre filtre"


def test_les_durees_par_defaut_sont_30_secondes_et_24_heures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in VARIABLES_DUREES:
        monkeypatch.delenv(variable, raising=False)

    config = Parametres(database_url=URL_BASE)

    assert config.cache_duree_fraiche == 30
    assert config.cache_duree_secours == 86400


def test_les_durees_du_cache_se_reglent_par_variables_d_environnement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CACHE_DUREE_FRAICHE", "1")
    monkeypatch.setenv("CACHE_DUREE_SECOURS", "5")

    config = Parametres(database_url=URL_BASE)

    assert config.cache_duree_fraiche == 1
    assert config.cache_duree_secours == 5
    for variable in VARIABLES_DUREES:
        for refusee in ("0", "-1"):
            monkeypatch.setenv(variable, refusee)
            with pytest.raises(ValidationError):
                Parametres(database_url=URL_BASE)
        monkeypatch.setenv(variable, "1")


# --- E5 : seuls les 200 sont mis en cache (D5) ------------------------------------------------


def _cas_404(semis: Any, inconnu: UUID) -> dict[str, tuple[str, Callable[[Any], object]]]:
    """Chemin qui répond 404 pour l'identifiant inconnu, et pose de cette ressource au dépôt."""
    evenement = semis.evenement
    return {
        "lireEvenement": (
            f"{ROUTE_EVENEMENTS}/{inconnu}",
            lambda depot: depot.semer_evenement(identifiant=inconnu),
        ),
        "listerSeances": (
            f"{ROUTE_EVENEMENTS}/{inconnu}/shows",
            lambda depot: depot.semer_evenement(identifiant=inconnu),
        ),
        "lireSeance": (
            f"{ROUTE_EVENEMENTS}/{evenement.id}/shows/{inconnu}",
            lambda depot: depot.semer_seance(evenement, semis.lieu, identifiant=inconnu),
        ),
        "lireSeanceParId": (
            f"/api/v1/shows/{inconnu}",
            lambda depot: depot.semer_seance(evenement, semis.lieu, identifiant=inconnu),
        ),
        "lireLieu": (
            f"/api/v1/venues/{inconnu}",
            lambda depot: depot.semer_lieu(identifiant=inconnu),
        ),
    }


LECTURES_404 = ["lireEvenement", "listerSeances", "lireSeance", "lireSeanceParId", "lireLieu"]


@pytest.mark.parametrize("operation", LECTURES_404)
async def test_un_404_n_est_pas_mis_en_cache(
    client: httpx.AsyncClient, depot: Any, semis: Any, operation: str
) -> None:
    inconnu = uuid4()
    chemin, poser = _cas_404(semis, inconnu)[operation]
    assert (await client.get(chemin)).status_code == 404
    poser(depot)

    reponse = await client.get(chemin)

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    if operation == "listerSeances":
        assert corps["total"] == 0
    else:
        assert corps["id"] == str(inconnu)


@pytest.mark.parametrize("operation", LECTURES_404)
async def test_un_404_lu_avant_la_panne_donne_503_pendant_la_panne(
    client: httpx.AsyncClient, depot: Any, cache: Any, semis: Any, operation: str
) -> None:
    chemin, _ = _cas_404(semis, uuid4())[operation]
    assert (await client.get(chemin)).status_code == 404
    cache.avancer(APRES_FRAICHEUR)
    depot.injoignable = True

    _assert_base_indisponible(await client.get(chemin))


async def test_un_422_ne_met_rien_en_cache(client: httpx.AsyncClient, cache: Any) -> None:
    chemins = [
        f"{ROUTE_EVENEMENTS}?size=0",
        f"{ROUTE_EVENEMENTS}?page=0",
        f"{ROUTE_EVENEMENTS}/pas-un-uuid",
        f"{ROUTE_EVENEMENTS}?du=2026-12-02T00:00:00%2B00:00&au=2026-12-01T00:00:00%2B00:00",
    ]
    for chemin in chemins:
        assert (await client.get(chemin)).status_code == 422, chemin

    assert cache.valeurs() == {}
    assert cache.generations == {}


# --- E7 : les places disponibles ne sont jamais mises en cache (D9) ---------------------------


def _proprietes(schemas: dict[str, Any], nom: str) -> set[str]:
    return set(schemas[nom]["properties"])


def _cles_recursives(valeur: Any) -> set[str]:
    if isinstance(valeur, dict):
        return set(valeur) | {cle for v in valeur.values() for cle in _cles_recursives(v)}
    if isinstance(valeur, list):
        return {cle for v in valeur for cle in _cles_recursives(v)}
    return set()


def _assert_seance_du_contrat(seance: dict[str, Any], schemas: dict[str, Any]) -> None:
    assert set(seance) == _proprietes(schemas, "Seance")
    for categorie in seance["categories"]:
        assert set(categorie) == _proprietes(schemas, "Categorie")
        for rang in categorie["rangs"]:
            assert set(rang) == _proprietes(schemas, "Rang")


async def test_une_seance_en_cache_ne_contient_que_les_champs_du_contrat(
    client: httpx.AsyncClient, cache: Any, semis: Any
) -> None:
    schemas = yaml.safe_load(CONTRAT_SERVICE.read_text(encoding="utf-8"))["components"]["schemas"]
    for operation in ("lireSeance", "lireSeanceParId", "listerSeances"):
        assert (await client.get(semis.lectures[operation])).status_code == 200

    valeurs = list(cache.valeurs().values())

    assert valeurs, "aucune valeur écrite dans le cache"
    for brute in valeurs:
        valeur = json.loads(brute)
        if "elements" in valeur:
            assert set(valeur) == _proprietes(schemas, "SeancePage")
            for seance in valeur["elements"]:
                _assert_seance_du_contrat(seance, schemas)
        else:
            _assert_seance_du_contrat(valeur, schemas)
        assert not [cle for cle in _cles_recursives(valeur) if "disponib" in cle.casefold()]
