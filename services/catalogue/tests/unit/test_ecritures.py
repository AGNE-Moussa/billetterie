"""Créations admin du catalogue (CA2, E4 du plan BIL-004), sans base ni Keycloak."""

import copy
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from commun.faux_jetons import EmetteurDeTest

pytestmark = pytest.mark.anyio

ROUTE_EVENEMENTS = "/api/v1/events"
ROUTE_LIEUX = "/api/v1/venues"

FabriqueSeance = Callable[..., dict[str, Any]]


def _assert_probleme(reponse: httpx.Response, statut: int, code: str) -> dict[str, Any]:
    assert reponse.status_code == statut, reponse.text
    assert reponse.headers["content-type"] == "application/problem+json"
    probleme: dict[str, Any] = reponse.json()
    assert probleme["code"] == code, probleme
    return probleme


def _a_un_fuseau(valeur: str) -> bool:
    return datetime.fromisoformat(valeur).utcoffset() is not None


def _route_seances(evenement_id: UUID) -> str:
    return f"{ROUTE_EVENEMENTS}/{evenement_id}/shows"


def _ecritures(depot: Any, seance_valide: FabriqueSeance) -> dict[str, tuple[str, dict[str, Any]]]:
    evenement = depot.semer_evenement()
    lieu = depot.semer_lieu()
    return {
        "creerEvenement": (
            ROUTE_EVENEMENTS,
            {"nom": "Concert de test", "description": "Description synthétique"},
        ),
        "creerLieu": (
            ROUTE_LIEUX,
            {"nom": "Salle de test", "adresse": "1 rue de l'Exemple", "ville": "Villetest"},
        ),
        "creerSeance": (_route_seances(evenement.id), seance_valide(lieu.id)),
    }


# --- CA2 : events:write exigé ---------------------------------------------------------------------


@pytest.mark.parametrize("appelant", ["client", "revendeur", "service"])
async def test_un_client_sans_events_write_ne_peut_pas_creer_d_evenement(
    anonyme: httpx.AsyncClient,
    depot: Any,
    evenement_valide: dict[str, str],
    request: pytest.FixtureRequest,
    appelant: str,
) -> None:
    entetes: dict[str, str] = request.getfixturevalue(f"entetes_{appelant}")
    avant = depot.instantane()

    reponse = await anonyme.post(ROUTE_EVENEMENTS, json=evenement_valide, headers=entetes)

    _assert_probleme(reponse, 403, "SCOPE_MANQUANT")
    assert depot.instantane() == avant


@pytest.mark.parametrize("operation", ["creerLieu", "creerSeance"])
async def test_un_client_sans_events_write_ne_peut_pas_creer_de_lieu_ni_de_seance(
    anonyme: httpx.AsyncClient,
    depot: Any,
    seance_valide: FabriqueSeance,
    entetes_client: dict[str, str],
    operation: str,
) -> None:
    chemin, corps = _ecritures(depot, seance_valide)[operation]
    avant = depot.instantane()

    reponse = await anonyme.post(chemin, json=corps, headers=entetes_client)

    _assert_probleme(reponse, 403, "SCOPE_MANQUANT")
    assert depot.instantane() == avant


@pytest.mark.parametrize("operation", ["creerEvenement", "creerLieu", "creerSeance"])
async def test_une_ecriture_sans_jeton_renvoie_401(
    anonyme: httpx.AsyncClient, depot: Any, seance_valide: FabriqueSeance, operation: str
) -> None:
    chemin, corps = _ecritures(depot, seance_valide)[operation]

    reponse = await anonyme.post(chemin, json=corps)

    _assert_probleme(reponse, 401, "JETON_ABSENT")
    assert reponse.headers["WWW-Authenticate"].startswith("Bearer")


@pytest.mark.parametrize(
    ("jeton", "code"), [("expire", "JETON_EXPIRE"), ("autre-emetteur", "JETON_INVALIDE")]
)
async def test_une_ecriture_avec_un_jeton_expire_ou_invalide_renvoie_401(
    anonyme: httpx.AsyncClient,
    emetteur: EmetteurDeTest,
    evenement_valide: dict[str, str],
    jeton: str,
    code: str,
) -> None:
    scopes = ["events:read", "events:write"]
    entetes = (
        emetteur.entetes(roles=["admin"], scopes=scopes, expire_dans=-3600)
        if jeton == "expire"
        else EmetteurDeTest().entetes(roles=["admin"], scopes=scopes)
    )

    reponse = await anonyme.post(ROUTE_EVENEMENTS, json=evenement_valide, headers=entetes)

    _assert_probleme(reponse, 401, code)


async def test_un_admin_avec_events_write_cree_un_evenement(
    anonyme: httpx.AsyncClient, evenement_valide: dict[str, str], entetes_admin: dict[str, str]
) -> None:
    reponse = await anonyme.post(ROUTE_EVENEMENTS, json=evenement_valide, headers=entetes_admin)

    assert reponse.status_code == 201, reponse.text
    assert reponse.headers["content-type"] == "application/json"
    corps = reponse.json()
    UUID(corps["id"])
    assert corps["nom"] == "Concert de test"
    assert corps["description"] == "Description synthétique"
    assert _a_un_fuseau(corps["cree_le"])


# --- E4 : créations et erreurs métier ------------------------------------------------------------


async def test_un_admin_cree_un_lieu(
    anonyme: httpx.AsyncClient, lieu_valide: dict[str, str], entetes_admin: dict[str, str]
) -> None:
    reponse = await anonyme.post(ROUTE_LIEUX, json=lieu_valide, headers=entetes_admin)

    assert reponse.status_code == 201, reponse.text
    corps = reponse.json()
    UUID(corps["id"])
    assert {k: corps[k] for k in ("nom", "adresse", "ville")} == lieu_valide
    assert _a_un_fuseau(corps["cree_le"])


@pytest.mark.parametrize(
    ("corps", "champ"),
    [
        ({"description": "Description synthétique"}, "nom"),
        ({"nom": "", "description": "Description synthétique"}, "nom"),
        ({"nom": "x" * 201, "description": "Description synthétique"}, "nom"),
        ({"nom": "Concert de test"}, "description"),
        ({"nom": "Concert de test", "description": "x" * 5001}, "description"),
    ],
    ids=["nom-absent", "nom-vide", "nom-201", "description-absente", "description-5001"],
)
async def test_un_corps_d_evenement_invalide_renvoie_422(
    anonyme: httpx.AsyncClient,
    depot: Any,
    entetes_admin: dict[str, str],
    corps: dict[str, str],
    champ: str,
) -> None:
    reponse = await anonyme.post(ROUTE_EVENEMENTS, json=corps, headers=entetes_admin)

    probleme = _assert_probleme(reponse, 422, "REQUETE_INVALIDE")
    assert any(e["champ"] == f"body.{champ}" for e in probleme["erreurs"]), probleme
    assert depot.evenements == {}


async def test_une_description_vide_est_acceptee(
    anonyme: httpx.AsyncClient, entetes_admin: dict[str, str]
) -> None:
    reponse = await anonyme.post(
        ROUTE_EVENEMENTS, json={"nom": "Concert de test", "description": ""}, headers=entetes_admin
    )

    assert reponse.status_code == 201, reponse.text
    assert reponse.json()["description"] == ""


LIEUX_INVALIDES = [
    (champ, cas, valeur)
    for champ, longueur in (("nom", 201), ("adresse", 301), ("ville", 101))
    for cas, valeur in (("absent", None), ("vide", ""), (f"{longueur}", "x" * longueur))
]


@pytest.mark.parametrize(
    ("champ", "cas", "valeur"), LIEUX_INVALIDES, ids=[f"{c}-{k}" for c, k, _ in LIEUX_INVALIDES]
)
async def test_un_corps_de_lieu_invalide_renvoie_422(
    anonyme: httpx.AsyncClient,
    depot: Any,
    lieu_valide: dict[str, str],
    entetes_admin: dict[str, str],
    champ: str,
    cas: str,
    valeur: str | None,
) -> None:
    corps: dict[str, Any] = dict(lieu_valide)
    if valeur is None:
        del corps[champ]
    else:
        corps[champ] = valeur

    reponse = await anonyme.post(ROUTE_LIEUX, json=corps, headers=entetes_admin)

    probleme = _assert_probleme(reponse, 422, "REQUETE_INVALIDE")
    assert any(e["champ"] == f"body.{champ}" for e in probleme["erreurs"]), probleme
    assert depot.lieux == {}


def _rangs(nombre: int) -> list[dict[str, Any]]:
    return [{"rang": f"R{i}", "nombre_places": 10} for i in range(nombre)]


def _categorie(nom: str, rangs: list[dict[str, Any]], prix: Any = 4500) -> dict[str, Any]:
    return {"nom": nom, "prix": prix, "rangs": rangs}


def _modifier(corps: dict[str, Any], cas: str) -> None:
    """Applique au corps de séance valide l'altération nommée par `cas`."""
    categorie = corps["categories"][0]
    match cas:
        case "categories-vide":
            corps["categories"] = []
        case "categories-21":
            corps["categories"] = [
                _categorie(f"Cat {i}", [{"rang": f"C{i}", "nombre_places": 1}]) for i in range(21)
            ]
        case "prix-0":
            categorie["prix"] = 0
        case "prix-negatif":
            categorie["prix"] = -1
        case "prix-decimal":
            categorie["prix"] = 12.5
        case "rangs-vide":
            categorie["rangs"] = []
        case "rangs-101":
            categorie["rangs"] = _rangs(101)
        case "rang-vide":
            categorie["rangs"][0]["rang"] = ""
        case "rang-11":
            categorie["rangs"][0]["rang"] = "x" * 11
        case "places-0":
            categorie["rangs"][0]["nombre_places"] = 0
        case "places-1001":
            categorie["rangs"][0]["nombre_places"] = 1001
        case "lieu-absent":
            del corps["lieu_id"]
        case "lieu-mal-forme":
            corps["lieu_id"] = "pas-un-uuid"
        case "debut-absent":
            del corps["debut"]
        case "debut-mal-forme":
            corps["debut"] = "demain soir"
        case _:
            raise AssertionError(cas)


SEANCES_INVALIDES = [
    "categories-vide",
    "categories-21",
    "prix-0",
    "prix-negatif",
    "prix-decimal",
    "rangs-vide",
    "rangs-101",
    "rang-vide",
    "rang-11",
    "places-0",
    "places-1001",
    "lieu-absent",
    "lieu-mal-forme",
    "debut-absent",
    "debut-mal-forme",
]


@pytest.mark.parametrize("cas", SEANCES_INVALIDES)
async def test_un_corps_de_seance_invalide_renvoie_422(
    anonyme: httpx.AsyncClient,
    depot: Any,
    seance_valide: FabriqueSeance,
    entetes_admin: dict[str, str],
    cas: str,
) -> None:
    evenement = depot.semer_evenement()
    corps = copy.deepcopy(seance_valide(depot.semer_lieu().id))
    _modifier(corps, cas)

    reponse = await anonyme.post(_route_seances(evenement.id), json=corps, headers=entetes_admin)

    _assert_probleme(reponse, 422, "REQUETE_INVALIDE")
    assert depot.seances == {}


async def test_les_bornes_hautes_de_seance_sont_acceptees(
    anonyme: httpx.AsyncClient,
    depot: Any,
    seance_valide: FabriqueSeance,
    entetes_admin: dict[str, str],
) -> None:
    evenement = depot.semer_evenement()
    corps = seance_valide(depot.semer_lieu().id)
    grande = _categorie("Grande", [{"rang": f"G{i:03d}", "nombre_places": 1} for i in range(100)])
    grande["rangs"][0] = {"rang": "x" * 10, "nombre_places": 1000}
    autres = [
        _categorie(f"Cat {i}", [{"rang": f"C{i}", "nombre_places": 1}], prix=1) for i in range(19)
    ]
    corps["categories"] = [grande, *autres]

    reponse = await anonyme.post(_route_seances(evenement.id), json=corps, headers=entetes_admin)

    assert reponse.status_code == 201, reponse.text
    assert len(reponse.json()["categories"]) == 20


async def test_une_seance_dans_le_passe_renvoie_422(
    anonyme: httpx.AsyncClient,
    depot: Any,
    seance_valide: FabriqueSeance,
    entetes_admin: dict[str, str],
    maintenant: datetime,
) -> None:
    evenement = depot.semer_evenement()
    corps = seance_valide(depot.semer_lieu().id, maintenant - timedelta(minutes=1))

    reponse = await anonyme.post(_route_seances(evenement.id), json=corps, headers=entetes_admin)

    _assert_probleme(reponse, 422, "SHOW_START_IN_PAST")
    assert depot.seances == {}


async def test_une_seance_qui_commence_maintenant_suit_la_regle_retenue(
    anonyme: httpx.AsyncClient,
    depot: Any,
    seance_valide: FabriqueSeance,
    entetes_admin: dict[str, str],
    maintenant: datetime,
) -> None:
    # Q9 : `debut` doit être strictement postérieur à l'instant de la requête (horloge figée).
    evenement = depot.semer_evenement()
    corps = seance_valide(depot.semer_lieu().id, maintenant)

    reponse = await anonyme.post(_route_seances(evenement.id), json=corps, headers=entetes_admin)

    _assert_probleme(reponse, 422, "SHOW_START_IN_PAST")
    assert depot.seances == {}


async def test_une_date_de_debut_sans_fuseau_suit_la_regle_retenue(
    anonyme: httpx.AsyncClient,
    depot: Any,
    seance_valide: FabriqueSeance,
    entetes_admin: dict[str, str],
) -> None:
    # Q8 : une date sans fuseau est refusée.
    evenement = depot.semer_evenement()
    corps = seance_valide(depot.semer_lieu().id)
    corps["debut"] = "2026-12-01T20:00:00"

    reponse = await anonyme.post(_route_seances(evenement.id), json=corps, headers=entetes_admin)

    probleme = _assert_probleme(reponse, 422, "REQUETE_INVALIDE")
    assert any(e["champ"] == "body.debut" for e in probleme["erreurs"]), probleme
    assert depot.seances == {}


async def test_un_rang_en_double_dans_une_categorie_renvoie_422(
    anonyme: httpx.AsyncClient,
    depot: Any,
    seance_valide: FabriqueSeance,
    entetes_admin: dict[str, str],
) -> None:
    evenement = depot.semer_evenement()
    corps = seance_valide(depot.semer_lieu().id)
    corps["categories"] = [
        _categorie(
            "Fosse", [{"rang": "A", "nombre_places": 10}, {"rang": "A", "nombre_places": 12}]
        )
    ]

    reponse = await anonyme.post(_route_seances(evenement.id), json=corps, headers=entetes_admin)

    _assert_probleme(reponse, 422, "ROW_ALREADY_ASSIGNED")
    assert depot.seances == {}


async def test_un_rang_dans_deux_categories_renvoie_422(
    anonyme: httpx.AsyncClient,
    depot: Any,
    seance_valide: FabriqueSeance,
    entetes_admin: dict[str, str],
) -> None:
    evenement = depot.semer_evenement()
    corps = seance_valide(depot.semer_lieu().id)
    corps["categories"] = [
        _categorie("Fosse", [{"rang": "A", "nombre_places": 10}]),
        _categorie("Balcon", [{"rang": "A", "nombre_places": 12}], prix=3000),
    ]

    reponse = await anonyme.post(_route_seances(evenement.id), json=corps, headers=entetes_admin)

    _assert_probleme(reponse, 422, "ROW_ALREADY_ASSIGNED")
    assert depot.seances == {}


async def test_l_unicite_des_rangs_suit_la_regle_de_comparaison_retenue(
    anonyme: httpx.AsyncClient,
    depot: Any,
    seance_valide: FabriqueSeance,
    entetes_admin: dict[str, str],
) -> None:
    # Q12 : comparaison exacte, `A` et `a` sont deux rangs distincts.
    evenement = depot.semer_evenement()
    corps = seance_valide(depot.semer_lieu().id)
    corps["categories"] = [
        _categorie(
            "Fosse", [{"rang": "A", "nombre_places": 10}, {"rang": "a", "nombre_places": 12}]
        )
    ]

    reponse = await anonyme.post(_route_seances(evenement.id), json=corps, headers=entetes_admin)

    assert reponse.status_code == 201, reponse.text
    rangs = [r["rang"] for r in reponse.json()["categories"][0]["rangs"]]
    assert rangs == ["A", "a"]


async def test_deux_categories_de_meme_nom_suivent_la_regle_retenue(
    anonyme: httpx.AsyncClient,
    depot: Any,
    seance_valide: FabriqueSeance,
    entetes_admin: dict[str, str],
) -> None:
    # Q13 : acceptées ; Q14 : ordre de la requête conservé.
    evenement = depot.semer_evenement()
    corps = seance_valide(depot.semer_lieu().id)
    corps["categories"] = [
        _categorie("Fosse", [{"rang": "A", "nombre_places": 10}]),
        _categorie("Fosse", [{"rang": "B", "nombre_places": 12}], prix=3000),
    ]

    reponse = await anonyme.post(_route_seances(evenement.id), json=corps, headers=entetes_admin)

    assert reponse.status_code == 201, reponse.text
    categories = reponse.json()["categories"]
    assert [(c["nom"], c["prix"]) for c in categories] == [("Fosse", 4500), ("Fosse", 3000)]
    assert categories[0]["id"] != categories[1]["id"]


async def test_une_seance_pour_un_evenement_inconnu_renvoie_404(
    anonyme: httpx.AsyncClient,
    depot: Any,
    seance_valide: FabriqueSeance,
    entetes_admin: dict[str, str],
) -> None:
    depot.semer_evenement()
    corps = seance_valide(depot.semer_lieu().id)

    reponse = await anonyme.post(_route_seances(uuid4()), json=corps, headers=entetes_admin)

    _assert_probleme(reponse, 404, "EVENT_NOT_FOUND")
    assert depot.seances == {}


async def test_une_seance_dans_un_lieu_inconnu_renvoie_404(
    anonyme: httpx.AsyncClient,
    depot: Any,
    seance_valide: FabriqueSeance,
    entetes_admin: dict[str, str],
) -> None:
    evenement = depot.semer_evenement()
    depot.semer_lieu()

    reponse = await anonyme.post(
        _route_seances(evenement.id), json=seance_valide(uuid4()), headers=entetes_admin
    )

    _assert_probleme(reponse, 404, "VENUE_NOT_FOUND")
    assert depot.seances == {}


@pytest.mark.parametrize(
    ("evenement_connu", "lieu_connu", "dans_le_passe", "rang_en_double", "code"),
    [
        (False, False, False, False, "EVENT_NOT_FOUND"),
        (True, False, True, False, "VENUE_NOT_FOUND"),
        (True, True, True, True, "SHOW_START_IN_PAST"),
    ],
    ids=[
        "evenement-et-lieu-inconnus",
        "lieu-inconnu-et-debut-passe",
        "debut-passe-et-rang-en-double",
    ],
)
async def test_les_erreurs_de_creation_de_seance_suivent_l_ordre_retenu(
    anonyme: httpx.AsyncClient,
    depot: Any,
    seance_valide: FabriqueSeance,
    entetes_admin: dict[str, str],
    maintenant: datetime,
    evenement_connu: bool,
    lieu_connu: bool,
    dans_le_passe: bool,
    rang_en_double: bool,
    code: str,
) -> None:
    # Q10 : REQUETE_INVALIDE, EVENT_NOT_FOUND, VENUE_NOT_FOUND, SHOW_START_IN_PAST,
    # ROW_ALREADY_ASSIGNED.
    evenement_id = depot.semer_evenement().id if evenement_connu else uuid4()
    lieu_id = depot.semer_lieu().id if lieu_connu else uuid4()
    debut = maintenant - timedelta(days=1) if dans_le_passe else None
    corps = seance_valide(lieu_id, debut)
    if rang_en_double:
        corps["categories"][0]["rangs"][1]["rang"] = "A"

    reponse = await anonyme.post(_route_seances(evenement_id), json=corps, headers=entetes_admin)

    _assert_probleme(reponse, 404 if code.endswith("NOT_FOUND") else 422, code)
    assert depot.seances == {}
