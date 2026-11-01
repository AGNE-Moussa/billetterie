"""Lectures publiques du catalogue (CA1, E2, E3 du plan BIL-004), sans base ni Keycloak."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.anyio

PREMIER_DEBUT = datetime(2026, 12, 1, 20, 0, tzinfo=UTC)
ROUTE_EVENEMENTS = "/api/v1/events"
ROUTE_LIEUX = "/api/v1/venues"
CHAMPS_PROBLEME = {"type", "title", "status", "detail", "code", "correlation_id", "erreurs"}


def _garnir(depot: Any) -> dict[str, str]:
    """Un événement, un lieu, une séance ; renvoie les chemins des sept lectures métier."""
    evenement = depot.semer_evenement()
    lieu = depot.semer_lieu()
    seance = depot.semer_seance(evenement, lieu)
    return {
        "listerEvenements": ROUTE_EVENEMENTS,
        "lireEvenement": f"{ROUTE_EVENEMENTS}/{evenement.id}",
        "listerSeances": f"{ROUTE_EVENEMENTS}/{evenement.id}/shows",
        "lireSeance": f"{ROUTE_EVENEMENTS}/{evenement.id}/shows/{seance.id}",
        "lireSeanceParId": f"/api/v1/shows/{seance.id}",
        "listerLieux": ROUTE_LIEUX,
        "lireLieu": f"{ROUTE_LIEUX}/{lieu.id}",
    }


LECTURES = [
    "listerEvenements",
    "lireEvenement",
    "listerSeances",
    "lireSeance",
    "lireSeanceParId",
    "listerLieux",
    "lireLieu",
]
LISTES = ["evenements", "lieux", "seances"]


def _semer_liste(depot: Any, liste: str, nombre: int) -> str:
    """`nombre` éléments dans la liste choisie ; renvoie la route de la liste."""
    if liste == "evenements":
        for rang in range(nombre):
            depot.semer_evenement(nom=f"Concert de test {rang:02d}")
        return ROUTE_EVENEMENTS
    if liste == "lieux":
        for rang in range(nombre):
            depot.semer_lieu(nom=f"Salle de test {rang:02d}")
        return ROUTE_LIEUX
    evenement = depot.semer_evenement()
    lieu = depot.semer_lieu()
    for rang in range(nombre):
        depot.semer_seance(evenement, lieu, PREMIER_DEBUT + timedelta(days=rang))
    return f"{ROUTE_EVENEMENTS}/{evenement.id}/shows"


def _assert_probleme(reponse: httpx.Response, statut: int, code: str) -> dict[str, Any]:
    assert reponse.status_code == statut, reponse.text
    assert reponse.headers["content-type"] == "application/problem+json"
    probleme: dict[str, Any] = reponse.json()
    assert probleme["code"] == code
    return probleme


# --- CA1 : routes du contrat ---------------------------------------------------------------------


@pytest.mark.parametrize("operation", LECTURES)
async def test_les_lectures_repondent_sans_jeton(
    anonyme: httpx.AsyncClient, depot: Any, operation: str
) -> None:
    chemin = _garnir(depot)[operation]

    reponse = await anonyme.get(chemin)

    assert "Authorization" not in reponse.request.headers
    assert reponse.status_code == 200, reponse.text
    assert reponse.headers["content-type"] == "application/json"


async def test_le_detail_d_un_evenement_ne_porte_ni_lieu_ni_seances(
    anonyme: httpx.AsyncClient, depot: Any
) -> None:
    evenement = depot.semer_evenement()

    reponse = await anonyme.get(f"{ROUTE_EVENEMENTS}/{evenement.id}")

    assert reponse.status_code == 200, reponse.text
    assert set(reponse.json()) == {"id", "nom", "description", "cree_le"}


def _modifications(depot: Any) -> list[tuple[str, str]]:
    evenement = depot.semer_evenement()
    lieu = depot.semer_lieu()
    seance = depot.semer_seance(evenement, lieu)
    chemins = [
        f"{ROUTE_EVENEMENTS}/{evenement.id}",
        f"{ROUTE_LIEUX}/{lieu.id}",
        f"{ROUTE_EVENEMENTS}/{evenement.id}/shows/{seance.id}",
    ]
    appels = [(methode, chemin) for chemin in chemins for methode in ("PUT", "PATCH", "DELETE")]
    appels.append(("POST", f"{ROUTE_EVENEMENTS}/{evenement.id}/shows/{seance.id}/cancel"))
    return appels


async def test_aucune_route_de_modification_ni_d_annulation_n_existe(
    anonyme: httpx.AsyncClient, depot: Any, entetes_admin: dict[str, str]
) -> None:
    appels = _modifications(depot)
    avant = (dict(depot.evenements), dict(depot.lieux), dict(depot.seances))

    for methode, chemin in appels:
        reponse = await anonyme.request(
            methode, chemin, headers=entetes_admin, json={"nom": "Modifié par le test"}
        )

        assert reponse.status_code in (404, 405), (methode, chemin, reponse.status_code)
        assert reponse.headers["content-type"] == "application/problem+json"
        assert set(reponse.json()) <= CHAMPS_PROBLEME
    assert (depot.evenements, depot.lieux, depot.seances) == avant


@pytest.mark.parametrize(
    "chemin",
    [
        f"{ROUTE_EVENEMENTS}/pas-un-uuid",
        f"{ROUTE_EVENEMENTS}/pas-un-uuid/shows",
        f"{ROUTE_EVENEMENTS}/{uuid4()}/shows/pas-un-uuid",
        "/api/v1/shows/pas-un-uuid",
        f"{ROUTE_LIEUX}/pas-un-uuid",
    ],
    ids=["evenement_id", "evenement_id-seances", "seance_id", "seance_id-direct", "lieu_id"],
)
async def test_les_identifiants_mal_formes_renvoient_422(
    anonyme: httpx.AsyncClient, chemin: str
) -> None:
    reponse = await anonyme.get(chemin)

    probleme = _assert_probleme(reponse, 422, "REQUETE_INVALIDE")
    assert probleme["erreurs"]


# --- E2 : pagination obligatoire, 404 ------------------------------------------------------------


@pytest.mark.parametrize("liste", LISTES)
async def test_les_listes_appliquent_la_pagination_par_defaut(
    anonyme: httpx.AsyncClient, depot: Any, liste: str
) -> None:
    route = _semer_liste(depot, liste, 25)

    reponse = await anonyme.get(route)

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert (corps["page"], corps["size"], corps["total"]) == (1, 20, 25)
    assert len(corps["elements"]) == 20


@pytest.mark.parametrize("liste", LISTES)
@pytest.mark.parametrize(("size", "nombre_attendu"), [(1, 1), (100, 25)])
async def test_les_listes_acceptent_les_bornes_de_size(
    anonyme: httpx.AsyncClient, depot: Any, liste: str, size: int, nombre_attendu: int
) -> None:
    route = _semer_liste(depot, liste, 25)

    reponse = await anonyme.get(route, params={"size": size})

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["size"] == size
    assert len(corps["elements"]) == nombre_attendu


@pytest.mark.parametrize("liste", LISTES)
@pytest.mark.parametrize(
    ("parametre", "valeur"),
    [("page", "0"), ("page", "-1"), ("size", "0"), ("size", "101"), ("size", "abc")],
)
async def test_les_listes_refusent_une_pagination_hors_bornes(
    anonyme: httpx.AsyncClient, depot: Any, liste: str, parametre: str, valeur: str
) -> None:
    route = _semer_liste(depot, liste, 1)

    reponse = await anonyme.get(route, params={parametre: valeur})

    probleme = _assert_probleme(reponse, 422, "REQUETE_INVALIDE")
    assert any(e["champ"] == f"query.{parametre}" for e in probleme["erreurs"])


@pytest.mark.parametrize("liste", LISTES)
async def test_une_page_au_dela_de_la_fin_est_vide(
    anonyme: httpx.AsyncClient, depot: Any, liste: str
) -> None:
    route = _semer_liste(depot, liste, 25)

    reponse = await anonyme.get(route, params={"page": 3, "size": 20})

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["elements"] == []
    assert corps["total"] == 25


@pytest.mark.parametrize("suffixe", ["", "/shows"], ids=["lireEvenement", "listerSeances"])
async def test_un_evenement_inconnu_renvoie_404(
    anonyme: httpx.AsyncClient, depot: Any, suffixe: str
) -> None:
    depot.semer_evenement()

    reponse = await anonyme.get(f"{ROUTE_EVENEMENTS}/{uuid4()}{suffixe}")

    _assert_probleme(reponse, 404, "EVENT_NOT_FOUND")


@pytest.mark.parametrize("operation", ["lireSeance", "lireSeanceParId"])
async def test_une_seance_inconnue_renvoie_404(
    anonyme: httpx.AsyncClient, depot: Any, operation: str
) -> None:
    evenement = depot.semer_evenement()
    depot.semer_seance(evenement, depot.semer_lieu())
    chemin = {
        "lireSeance": f"{ROUTE_EVENEMENTS}/{evenement.id}/shows/{uuid4()}",
        "lireSeanceParId": f"/api/v1/shows/{uuid4()}",
    }[operation]

    reponse = await anonyme.get(chemin)

    _assert_probleme(reponse, 404, "SHOW_NOT_FOUND")


async def test_une_seance_lue_sous_un_evenement_inconnu_renvoie_event_not_found(
    anonyme: httpx.AsyncClient, depot: Any
) -> None:
    seance = depot.semer_seance(depot.semer_evenement(), depot.semer_lieu())

    reponse = await anonyme.get(f"{ROUTE_EVENEMENTS}/{uuid4()}/shows/{seance.id}")

    _assert_probleme(reponse, 404, "EVENT_NOT_FOUND")


async def test_une_seance_lue_sous_un_autre_evenement_renvoie_show_not_found(
    anonyme: httpx.AsyncClient, depot: Any
) -> None:
    premier = depot.semer_evenement(nom="Concert de test")
    second = depot.semer_evenement(nom="Théâtre synthétique")
    seance_du_second = depot.semer_seance(second, depot.semer_lieu())

    reponse = await anonyme.get(f"{ROUTE_EVENEMENTS}/{premier.id}/shows/{seance_du_second.id}")

    _assert_probleme(reponse, 404, "SHOW_NOT_FOUND")


async def test_un_lieu_inconnu_renvoie_404(anonyme: httpx.AsyncClient, depot: Any) -> None:
    depot.semer_lieu()

    reponse = await anonyme.get(f"{ROUTE_LIEUX}/{uuid4()}")

    _assert_probleme(reponse, 404, "VENUE_NOT_FOUND")


# --- E3 : filtres de recherche -------------------------------------------------------------------


async def test_du_posterieur_a_au_renvoie_422(
    anonyme: httpx.AsyncClient, depot: Any, maintenant: Any
) -> None:
    depot.semer_evenement()
    parametres = {
        "du": (maintenant + timedelta(days=20)).isoformat(),
        "au": (maintenant + timedelta(days=10)).isoformat(),
    }

    reponse = await anonyme.get(ROUTE_EVENEMENTS, params=parametres)

    probleme = _assert_probleme(reponse, 422, "REQUETE_INVALIDE")
    # S1 : `erreurs` nomme le paramètre fautif, comme une erreur de validation.
    assert probleme.get("erreurs"), probleme
    assert any(e["champ"].split(".")[-1] in {"du", "au"} for e in probleme["erreurs"])


@pytest.mark.parametrize(
    ("parametre", "valeur"),
    [("q", ""), ("q", "x" * 101), ("ville", ""), ("ville", "x" * 101)],
    ids=["q-vide", "q-101", "ville-vide", "ville-101"],
)
async def test_des_filtres_hors_longueur_renvoient_422(
    anonyme: httpx.AsyncClient, parametre: str, valeur: str
) -> None:
    reponse = await anonyme.get(ROUTE_EVENEMENTS, params={parametre: valeur})

    _assert_probleme(reponse, 422, "REQUETE_INVALIDE")


async def test_une_date_de_filtre_mal_formee_renvoie_422(anonyme: httpx.AsyncClient) -> None:
    reponse = await anonyme.get(ROUTE_EVENEMENTS, params={"du": "demain"})

    _assert_probleme(reponse, 422, "REQUETE_INVALIDE")


async def test_une_date_de_filtre_sans_fuseau_suit_la_regle_retenue(
    anonyme: httpx.AsyncClient,
) -> None:
    # Q8 : une date sans fuseau est refusée.
    reponse = await anonyme.get(ROUTE_EVENEMENTS, params={"du": "2026-12-01T20:00:00"})

    _assert_probleme(reponse, 422, "REQUETE_INVALIDE")


async def test_un_filtre_par_categorie_n_existe_pas(anonyme: httpx.AsyncClient, depot: Any) -> None:
    evenement = depot.semer_evenement()
    depot.semer_seance(evenement, depot.semer_lieu())
    depot.semer_evenement(nom="Exposition sans séance")

    sans_filtre = await anonyme.get(ROUTE_EVENEMENTS)
    avec_categorie = await anonyme.get(ROUTE_EVENEMENTS, params={"categorie": "Fosse"})

    assert sans_filtre.status_code == 200, sans_filtre.text
    assert avec_categorie.status_code == 200, avec_categorie.text
    assert avec_categorie.json() == sans_filtre.json()
    assert avec_categorie.json()["total"] == 2
