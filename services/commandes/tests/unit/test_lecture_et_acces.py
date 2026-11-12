"""Lecture des commandes, isolement des appelants et contrôle d'accès (E4 du plan BIL-008 ;
décision Q7, rules/securite.md)."""

from datetime import timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest

from commandes.domaine.commandes import StatutCommande

pytestmark = pytest.mark.anyio

ORDERS = "/api/v1/orders"
CARTE_ACCEPTEE = "4242424242424242"


def _ids(reponse: httpx.Response) -> list[str]:
    return [element["id"] for element in reponse.json()["elements"]]


async def test_lister_mes_commandes_ne_rend_que_celles_de_l_appelant(
    client: httpx.AsyncClient, seance: Any, entetes_a: dict[str, str], depot: Any
) -> None:
    a = {str(depot.semer("client-a", seance.id, StatutCommande.CONFIRMEE).id) for _ in range(3)}
    b = {str(depot.semer("client-b", seance.id, StatutCommande.CONFIRMEE).id) for _ in range(2)}

    reponse = await client.get(ORDERS, headers=entetes_a)

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["total"] == 3
    assert set(_ids(reponse)) == a
    assert not set(_ids(reponse)) & b


async def test_un_parametre_de_requete_ne_change_pas_l_appelant(
    client: httpx.AsyncClient, seance: Any, entetes_a: dict[str, str], depot: Any
) -> None:
    a = {str(depot.semer("client-a", seance.id, StatutCommande.CONFIRMEE).id) for _ in range(2)}
    depot.semer("client-b", seance.id, StatutCommande.CONFIRMEE)
    depot.semer("sujet-revendeur-test", seance.id, StatutCommande.CONFIRMEE)

    reponse = await client.get(
        ORDERS,
        params={"client": "client-b", "revendeur": "revendeur-test"},
        headers=entetes_a,
    )

    assert reponse.status_code == 200, reponse.text
    assert set(_ids(reponse)) == a
    assert reponse.json()["total"] == 2


async def test_un_revendeur_ne_voit_que_ses_propres_commandes(
    client: httpx.AsyncClient, seance: Any, entetes_r1: dict[str, str], depot: Any
) -> None:
    r1 = {
        str(depot.semer("sujet-revendeur-test", seance.id, StatutCommande.CONFIRMEE).id)
        for _ in range(2)
    }
    depot.semer("sujet-revendeur-test-2", seance.id, StatutCommande.CONFIRMEE)
    depot.semer("client-a", seance.id, StatutCommande.CONFIRMEE)

    reponse = await client.get(ORDERS, headers=entetes_r1)

    assert reponse.status_code == 200, reponse.text
    assert set(_ids(reponse)) == r1
    assert reponse.json()["total"] == 2


async def test_les_commandes_sont_triees_par_creation_decroissante_puis_identifiant(
    client: httpx.AsyncClient, seance: Any, entetes_a: dict[str, str], depot: Any, horloge: Any
) -> None:
    for rang in range(24):
        depot.semer(
            "client-a",
            seance.id,
            StatutCommande.CONFIRMEE,
            cree_le=horloge.maintenant - timedelta(minutes=rang),
        )
    # Deux commandes de même cree_le : l'identifiant départage.
    depot.semer("client-a", seance.id, StatutCommande.CONFIRMEE, cree_le=horloge.maintenant)

    page_1 = await client.get(ORDERS, headers=entetes_a)
    page_1_bis = await client.get(ORDERS, headers=entetes_a)
    page_2 = await client.get(ORDERS, params={"page": 2}, headers=entetes_a)

    assert page_1.status_code == 200, page_1.text
    corps = page_1.json()
    assert (corps["page"], corps["size"], corps["total"]) == (1, 20, 25)
    assert len(corps["elements"]) == 20
    assert _ids(page_1) == _ids(page_1_bis)
    assert len(page_2.json()["elements"]) == 5
    tous = corps["elements"] + page_2.json()["elements"]
    assert len({e["id"] for e in tous}) == 25
    dates = [e["cree_le"] for e in tous]
    assert dates == sorted(dates, reverse=True)


@pytest.mark.parametrize("parametres", [{"page": 0}, {"size": 0}, {"size": 101}])
async def test_une_pagination_invalide_renvoie_422(
    client: httpx.AsyncClient, entetes_a: dict[str, str], parametres: dict[str, int]
) -> None:
    reponse = await client.get(ORDERS, params=parametres, headers=entetes_a)

    assert reponse.status_code == 422, reponse.text
    assert reponse.json()["code"] == "REQUETE_INVALIDE"


@pytest.mark.parametrize(
    ("proprietaire", "lecteur", "action"),
    [
        ("client-a", "b", "lire"),
        ("client-a", "b", "payer"),
        ("sujet-revendeur-test", "r2", "lire"),
    ],
)
async def test_la_commande_d_un_autre_renvoie_404(
    client: httpx.AsyncClient,
    seance: Any,
    depot: Any,
    journal: Any,
    entetes_b: dict[str, str],
    entetes_r2: dict[str, str],
    proprietaire: str,
    lecteur: str,
    action: str,
) -> None:
    commande = depot.semer(
        proprietaire, seance.id, StatutCommande.EN_ATTENTE, place_ids=[seance["A1"]]
    )
    entetes = entetes_b if lecteur == "b" else entetes_r2

    if action == "lire":
        reponse = await client.get(f"{ORDERS}/{commande.id}", headers=entetes)
    else:
        reponse = await client.post(
            f"{ORDERS}/{commande.id}/payment",
            json={"carte_test": CARTE_ACCEPTEE},
            headers=entetes,
        )

    assert reponse.status_code == 404, reponse.text
    assert reponse.json()["code"] == "ORDER_NOT_FOUND"
    assert journal.de("paiements") == []
    assert depot.commandes[commande.id].statut is StatutCommande.EN_ATTENTE


async def test_une_commande_inconnue_renvoie_404(
    client: httpx.AsyncClient, entetes_a: dict[str, str]
) -> None:
    reponse = await client.get(f"{ORDERS}/{uuid4()}", headers=entetes_a)

    assert reponse.status_code == 404, reponse.text
    assert reponse.json()["code"] == "ORDER_NOT_FOUND"


def _requete(route: str, seance: Any) -> tuple[str, str, dict[str, Any] | None]:
    commande_id = uuid4()
    if route == "creer":
        return "POST", ORDERS, seance.corps("A1")
    if route == "lister":
        return "GET", ORDERS, None
    if route == "lire":
        return "GET", f"{ORDERS}/{commande_id}", None
    return "POST", f"{ORDERS}/{commande_id}/payment", {"carte_test": CARTE_ACCEPTEE}


CAS_ACCES = [
    # (cas, route, statut, code)
    *[("sans_jeton", r, 401, "JETON_ABSENT") for r in ("creer", "lister", "lire", "payer")],
    ("jeton_expire", "creer", 401, "JETON_EXPIRE"),
    ("jeton_expire", "lister", 401, "JETON_EXPIRE"),
    ("x_user_id_different", "creer", 401, "JETON_INVALIDE"),
    ("x_user_id_different", "lire", 401, "JETON_INVALIDE"),
    *[("admin", r, 403, "SCOPE_MANQUANT") for r in ("creer", "lister", "lire", "payer")],
    ("sans_orders_write", "creer", 403, "SCOPE_MANQUANT"),
    ("sans_orders_write", "payer", 403, "SCOPE_MANQUANT"),
    ("sans_orders_read", "lister", 403, "SCOPE_MANQUANT"),
    ("sans_orders_read", "lire", 403, "SCOPE_MANQUANT"),
]


@pytest.mark.parametrize(
    ("cas", "route", "statut", "code"),
    CAS_ACCES,
    ids=[f"{cas}-{route}" for cas, route, _, _ in CAS_ACCES],
)
async def test_le_controle_d_acces_des_routes_de_commandes(
    client: httpx.AsyncClient,
    seance: Any,
    emetteur: Any,
    entetes_admin: dict[str, str],
    journal: Any,
    depot: Any,
    cas: str,
    route: str,
    statut: int,
    code: str,
) -> None:
    client_a = {"sujet": "client-a", "roles": ["customer"], "email": "client.test@exemple.test"}
    if cas == "sans_jeton":
        entetes: dict[str, str] = {}
    elif cas == "jeton_expire":
        entetes = emetteur.entetes(
            **client_a, scopes=["orders:read", "orders:write"], expire_dans=-60
        )
    elif cas == "x_user_id_different":
        entetes = {
            **emetteur.entetes(**client_a, scopes=["orders:read", "orders:write"]),
            "X-User-Id": "client-b",
        }
    elif cas == "admin":
        entetes = entetes_admin
    elif cas == "sans_orders_write":
        entetes = emetteur.entetes(**client_a, scopes=["orders:read"])
    else:
        entetes = emetteur.entetes(**client_a, scopes=["orders:write"])
    methode, chemin, corps = _requete(route, seance)

    reponse = await client.request(methode, chemin, json=corps, headers=entetes)

    assert reponse.status_code == statut, reponse.text
    assert reponse.json()["code"] == code
    assert journal.appels == []
    assert depot.commandes == {}
