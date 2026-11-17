"""Idempotency-Key de creerCommande, payerCommande et indisponibilités (CA2, E3, E5, E7 du plan
BIL-008 ; décisions Q10, Q12, Q14, Q16, Q18)."""

from datetime import timedelta
from typing import Any

import httpx
import pytest

from commandes.domaine.commandes import EVENEMENT_COMMANDE_EXPIREE, StatutCommande

pytestmark = pytest.mark.anyio

ORDERS = "/api/v1/orders"
CARTE_ACCEPTEE = "4242424242424242"
CARTE_REFUSEE = "4000000000000002"


def _payer(commande_id: Any) -> str:
    return f"{ORDERS}/{commande_id}/payment"


# --- E3 : Idempotency-Key -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("premiere", "statut_premiere", "statut_rendu"),
    [("refus", 402, "EXPIREE"), ("panne", 503, "EN_ATTENTE")],
)
async def test_rejouer_une_commande_refusee_ou_en_attente_rend_son_etat(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    depot: Any,
    paiements: Any,
    premiere: str,
    statut_premiere: int,
    statut_rendu: str,
) -> None:
    entetes = {**entetes_a, "Idempotency-Key": "cle-bil-008-rejeu"}
    carte = CARTE_REFUSEE if premiere == "refus" else CARTE_ACCEPTEE
    paiements.en_panne = premiere == "panne"

    reponse_1 = await client.post(ORDERS, json=seance.corps("A1", carte=carte), headers=entetes)
    # Corps différent au rejeu : il est ignoré.
    reponse_2 = await client.post(
        ORDERS, json=seance.corps("A2", carte=CARTE_ACCEPTEE), headers=entetes
    )

    assert reponse_1.status_code == statut_premiere, reponse_1.text
    assert reponse_2.status_code == 200, reponse_2.text
    commandes = depot.commandes_de("client-a")
    assert len(commandes) == 1
    assert reponse_2.json()["id"] == str(commandes[0].id)
    assert reponse_2.json()["statut"] == statut_rendu
    assert [ligne["place_id"] for ligne in reponse_2.json()["lignes"]] == [str(seance["A1"])]


async def test_la_meme_cle_par_un_autre_client_cree_une_autre_commande(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    entetes_b: dict[str, str],
) -> None:
    cle = {"Idempotency-Key": "cle-bil-008-partagee"}

    reponse_a = await client.post(ORDERS, json=seance.corps("A1"), headers={**entetes_a, **cle})
    reponse_b = await client.post(ORDERS, json=seance.corps("A2"), headers={**entetes_b, **cle})

    assert reponse_a.status_code == 201, reponse_a.text
    assert reponse_b.status_code == 201, reponse_b.text
    assert reponse_a.json()["id"] != reponse_b.json()["id"]


async def test_une_cle_de_plus_de_cent_caracteres_renvoie_422(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    depot: Any,
    journal: Any,
) -> None:
    entetes = {**entetes_a, "Idempotency-Key": "k" * 101}

    reponse = await client.post(ORDERS, json=seance.corps("A1"), headers=entetes)

    assert reponse.status_code == 422, reponse.text
    assert reponse.json()["code"] == "REQUETE_INVALIDE"
    assert depot.commandes_de("client-a") == []
    assert journal.appels == []


# --- CA2 et E5 : payerCommande ------------------------------------------------------------------


@pytest.mark.parametrize("statut", [StatutCommande.CONFIRMEE, StatutCommande.EXPIREE])
async def test_payer_une_commande_non_en_attente_renvoie_409_order_not_pending(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    depot: Any,
    journal: Any,
    statut: StatutCommande,
) -> None:
    commande = depot.semer(
        "client-a", seance.id, statut, place_ids=[seance["A1"]], email="client.test@exemple.test"
    )

    reponse = await client.post(
        _payer(commande.id), json={"carte_test": CARTE_ACCEPTEE}, headers=entetes_a
    )

    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["code"] == "ORDER_NOT_PENDING"
    assert journal.de("paiements") == []
    assert depot.commandes[commande.id].statut is statut


@pytest.mark.parametrize(
    ("situation", "code"), [("annulee", "SHOW_CANCELLED"), ("commencee", "SHOW_ALREADY_STARTED")]
)
async def test_payer_une_commande_d_une_seance_annulee_ou_commencee_renvoie_409(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    depot: Any,
    catalogue: Any,
    horloge: Any,
    journal: Any,
    situation: str,
    code: str,
) -> None:
    commande = depot.semer(
        "client-a",
        seance.id,
        StatutCommande.EN_ATTENTE,
        place_ids=[seance["A1"]],
        email="client.test@exemple.test",
    )
    if situation == "annulee":
        catalogue.seances[seance.id]["annulee"] = True
    else:
        debut = horloge.maintenant - timedelta(minutes=5)
        catalogue.seances[seance.id]["debut"] = debut.isoformat()

    reponse = await client.post(
        _payer(commande.id), json={"carte_test": CARTE_ACCEPTEE}, headers=entetes_a
    )

    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["code"] == code
    assert journal.de("paiements") == []


# --- E7 : indisponibilités ----------------------------------------------------------------------


@pytest.mark.parametrize("route", ["creerCommande", "payerCommande"])
async def test_catalogue_indisponible_renvoie_503_sans_commande(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    depot: Any,
    catalogue: Any,
    journal: Any,
    route: str,
) -> None:
    catalogue.en_panne = True
    en_attente = None
    if route == "creerCommande":
        reponse = await client.post(ORDERS, json=seance.corps("A1"), headers=entetes_a)
    else:
        en_attente = depot.semer(
            "client-a", seance.id, StatutCommande.EN_ATTENTE, place_ids=[seance["A1"]]
        )
        reponse = await client.post(
            _payer(en_attente.id), json={"carte_test": CARTE_ACCEPTEE}, headers=entetes_a
        )

    assert reponse.status_code == 503, reponse.text
    assert reponse.json()["code"] == "SERVICE_INDISPONIBLE"
    assert journal.de("paiements") == []
    if en_attente is None:
        assert depot.commandes_de("client-a") == []
    else:
        assert [c.id for c in depot.commandes_de("client-a")] == [en_attente.id]
        assert depot.commandes[en_attente.id].statut is StatutCommande.EN_ATTENTE


@pytest.mark.parametrize(
    ("moment", "statut_attendu"),
    [("reservation", StatutCommande.EXPIREE), ("reverrouillage", StatutCommande.EN_ATTENTE)],
)
async def test_billets_indisponible_renvoie_503(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    depot: Any,
    billets: Any,
    journal: Any,
    moment: str,
    statut_attendu: StatutCommande,
) -> None:
    if moment == "reservation":
        billets.panne_reservation = True
    else:
        billets.panne_confirmation = True
    corps = seance.corps("A1", "C1")

    reponse = await client.post(ORDERS, json=corps, headers=entetes_a)

    assert reponse.status_code == 503, reponse.text
    assert reponse.json()["code"] == "SERVICE_INDISPONIBLE"
    commandes = depot.commandes_de("client-a")
    assert [c.statut for c in commandes] == [statut_attendu]
    assert journal.de("paiements") == []
    expirees = depot.evenements_de(EVENEMENT_COMMANDE_EXPIREE)
    if statut_attendu is StatutCommande.EXPIREE:
        assert len(expirees) == 1
        assert expirees[0].data["commande_id"] == str(commandes[0].id)
        assert set(expirees[0].data["place_ids"]) == set(corps["place_ids"])
    else:
        assert depot.evenements == []


async def test_keycloak_indisponible_renvoie_503(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    keycloak: Any,
    journal: Any,
) -> None:
    keycloak.en_panne = True

    reponse = await client.post(ORDERS, json=seance.corps("A1"), headers=entetes_a)

    assert reponse.status_code == 503, reponse.text
    assert reponse.json()["code"] == "SERVICE_INDISPONIBLE"
    assert journal.de("billets") == []
    assert journal.de("paiements") == []
