"""creerCommande sans carte_test (BIL-020, Q1 de BIL-018).

Sans carte : 201 EN_ATTENTE, places verrouillées en durée de réservation jusqu'à expire_le,
aucun appel à Paiements ni reverrouillage de confirmation ; la commande se paie ensuite par
payerCommande. Avec carte : comportement inchangé (appel unique, CONFIRMEE).
"""

from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest

from commandes.domaine.commandes import EVENEMENT_COMMANDE_CONFIRMEE, StatutCommande

pytestmark = pytest.mark.anyio

ORDERS = "/api/v1/orders"
CARTE_ACCEPTEE = "4242424242424242"
CARTE_REFUSEE = "4000000000000002"
DUREE_RESERVATION = 600
DUREE_CONFIRMATION = 3600


def _sans_carte(seance: Any, *noms: str, explicite: bool = False) -> dict[str, Any]:
    corps = seance.corps(*noms)
    if explicite:
        corps["carte_test"] = None
    else:
        del corps["carte_test"]
    return corps


def _payer(commande_id: Any) -> str:
    return f"{ORDERS}/{commande_id}/payment"


@pytest.mark.parametrize("explicite", [False, True], ids=["absente", "null"])
async def test_sans_carte_la_commande_est_creee_en_attente_avec_son_echeance(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    horloge: Any,
    depot: Any,
    explicite: bool,
) -> None:
    reponse = await client.post(
        ORDERS, json=_sans_carte(seance, "A1", "C1", explicite=explicite), headers=entetes_a
    )

    assert reponse.status_code == 201, reponse.text
    commande = reponse.json()
    assert commande["statut"] == "EN_ATTENTE"
    assert commande["montant_total"] == 7500
    attendue = horloge.maintenant + timedelta(seconds=DUREE_RESERVATION)
    assert datetime.fromisoformat(commande["expire_le"]) == attendue
    enregistree = depot.commandes_de("client-a")
    assert [(c.statut, c.expire_le) for c in enregistree] == [(StatutCommande.EN_ATTENTE, attendue)]


async def test_sans_carte_aucun_appel_a_paiements_ni_reverrouillage_ni_confirmation(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    journal: Any,
    depot: Any,
) -> None:
    reponse = await client.post(ORDERS, json=_sans_carte(seance, "A1", "C1"), headers=entetes_a)

    assert reponse.status_code == 201, reponse.text
    assert journal.de("paiements") == []
    verrous = journal.de("billets")
    assert len(verrous) == 2
    assert all(a.corps.get("confirmation", False) is False for a in verrous)
    assert depot.evenements_de(EVENEMENT_COMMANDE_CONFIRMEE) == []


async def test_avec_carte_la_commande_reste_payee_en_un_appel(
    client: httpx.AsyncClient, seance: Any, entetes_a: dict[str, str], journal: Any
) -> None:
    reponse = await client.post(ORDERS, json=seance.corps("A1"), headers=entetes_a)

    assert reponse.status_code == 201, reponse.text
    assert reponse.json()["statut"] == "CONFIRMEE"
    assert len(journal.de("paiements")) == 1


async def test_un_revendeur_peut_aussi_commander_sans_carte(
    client: httpx.AsyncClient, seance: Any, entetes_r1: dict[str, str], journal: Any
) -> None:
    reponse = await client.post(ORDERS, json=_sans_carte(seance, "A1"), headers=entetes_r1)

    assert reponse.status_code == 201, reponse.text
    assert reponse.json()["statut"] == "EN_ATTENTE"
    assert journal.de("paiements") == []


async def test_sans_carte_une_place_prise_renvoie_409_et_expire_la_commande(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    entetes_b: dict[str, str],
    depot: Any,
) -> None:
    premiere = await client.post(ORDERS, json=_sans_carte(seance, "A1"), headers=entetes_a)
    seconde = await client.post(ORDERS, json=_sans_carte(seance, "A1"), headers=entetes_b)

    assert premiere.status_code == 201, premiere.text
    assert seconde.status_code == 409, seconde.text
    assert seconde.json()["code"] == "SEAT_ALREADY_TAKEN"
    assert [c.statut for c in depot.commandes_de("client-b")] == [StatutCommande.EXPIREE]


async def test_le_rejeu_idempotent_d_une_commande_sans_carte_rend_l_etat_courant(
    client: httpx.AsyncClient, seance: Any, entetes_a: dict[str, str], journal: Any
) -> None:
    entetes = {**entetes_a, "Idempotency-Key": "cle-bil-020-rejeu"}

    premiere = await client.post(ORDERS, json=_sans_carte(seance, "A1"), headers=entetes)
    payee = await client.post(
        _payer(premiere.json()["id"]), json={"carte_test": CARTE_ACCEPTEE}, headers=entetes_a
    )
    rejeu = await client.post(ORDERS, json=_sans_carte(seance, "A1"), headers=entetes)

    assert premiere.status_code == 201, premiere.text
    assert payee.status_code == 200, payee.text
    assert rejeu.status_code == 200, rejeu.text
    assert rejeu.json()["id"] == premiere.json()["id"]
    assert rejeu.json()["statut"] == "CONFIRMEE"
    assert len(journal.de("paiements")) == 1


async def test_payer_une_commande_creee_sans_carte_la_confirme(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    journal: Any,
    depot: Any,
    horloge: Any,
) -> None:
    creee = await client.post(ORDERS, json=_sans_carte(seance, "A1", "C1"), headers=entetes_a)
    commande_id = creee.json()["id"]
    journal.appels.clear()

    reponse = await client.post(
        _payer(commande_id), json={"carte_test": CARTE_ACCEPTEE}, headers=entetes_a
    )

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["statut"] == "CONFIRMEE"
    assert reponse.json()["montant_total"] == 7500
    confirmations = journal.de("billets")
    assert len(confirmations) == 2
    assert all(a.corps["confirmation"] is True for a in confirmations)
    paiements = journal.de("paiements")
    assert len(paiements) == 1
    assert paiements[0].corps["montant"] == 7500
    assert paiements[0].corps["commande_id"] == commande_id
    commande = next(iter(depot.commandes.values()))
    assert commande.statut is StatutCommande.CONFIRMEE
    assert commande.expire_le == horloge.maintenant + timedelta(seconds=DUREE_CONFIRMATION)
    assert len(depot.evenements_de(EVENEMENT_COMMANDE_CONFIRMEE)) == 1


async def test_payer_une_commande_sans_carte_avec_une_carte_refusee_l_expire(
    client: httpx.AsyncClient, seance: Any, entetes_a: dict[str, str], depot: Any
) -> None:
    creee = await client.post(ORDERS, json=_sans_carte(seance, "A1"), headers=entetes_a)

    reponse = await client.post(
        _payer(creee.json()["id"]), json={"carte_test": CARTE_REFUSEE}, headers=entetes_a
    )

    assert reponse.status_code == 402, reponse.text
    assert reponse.json()["code"] == "PAYMENT_REFUSED"
    assert [c.statut for c in depot.commandes_de("client-a")] == [StatutCommande.EXPIREE]


async def test_payer_sans_carte_dans_le_corps_renvoie_422(
    client: httpx.AsyncClient, seance: Any, entetes_a: dict[str, str], journal: Any
) -> None:
    creee = await client.post(ORDERS, json=_sans_carte(seance, "A1"), headers=entetes_a)
    journal.appels.clear()

    reponse = await client.post(_payer(creee.json()["id"]), json={}, headers=entetes_a)

    assert reponse.status_code == 422, reponse.text
    assert reponse.json()["code"] == "REQUETE_INVALIDE"
    assert journal.appels == []


async def test_un_autre_client_ne_peut_pas_payer_une_commande_creee_sans_carte(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    entetes_b: dict[str, str],
    journal: Any,
) -> None:
    creee = await client.post(ORDERS, json=_sans_carte(seance, "A1"), headers=entetes_a)

    reponse = await client.post(
        _payer(creee.json()["id"]), json={"carte_test": CARTE_ACCEPTEE}, headers=entetes_b
    )

    assert reponse.status_code == 404, reponse.text
    assert reponse.json()["code"] == "ORDER_NOT_FOUND"
    assert journal.de("paiements") == []
