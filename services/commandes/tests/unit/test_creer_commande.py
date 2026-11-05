"""creerCommande : verrous au nom de la commande, prix des lignes, appel à Paiements (CA1, CA2,
E8 du plan BIL-008 ; décisions Q1, Q2, Q4, Q6, Q13)."""

from datetime import timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest

from commandes.domaine.commandes import EVENEMENT_COMMANDE_EXPIREE, StatutCommande

pytestmark = pytest.mark.anyio

ORDERS = "/api/v1/orders"


async def test_une_commande_de_places_libres_est_confirmee_au_prix_de_leur_categorie(
    client: httpx.AsyncClient, seance: Any, entetes_a: dict[str, str]
) -> None:
    reponse = await client.post(ORDERS, json=seance.corps("A1", "C1"), headers=entetes_a)

    assert reponse.status_code == 201, reponse.text
    commande = reponse.json()
    assert commande["statut"] == "CONFIRMEE"
    assert commande["seance_id"] == str(seance.id)
    montants = {ligne["place_id"]: ligne["montant"] for ligne in commande["lignes"]}
    assert montants == {str(seance["A1"]): 4500, str(seance["C1"]): 3000}
    assert commande["montant_total"] == 7500


async def test_commandes_verrouille_chaque_place_au_nom_de_la_commande_puis_la_confirme_avant_de_payer(  # noqa: E501
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    journal: Any,
    keycloak: Any,
) -> None:
    reponse = await client.post(ORDERS, json=seance.corps("A1", "C1"), headers=entetes_a)

    assert reponse.status_code == 201, reponse.text
    commande_id = reponse.json()["id"]
    places = {str(seance["A1"]), str(seance["C1"])}
    sortants = [a for a in journal.appels if a.cible in ("billets", "paiements")]
    verrous = [a for a in sortants if a.cible == "billets"]
    assert all(a.methode == "PUT" for a in verrous)
    reservations = [a for a in verrous if not a.corps.get("confirmation", False)]
    confirmations = [a for a in verrous if a.corps.get("confirmation") is True]
    assert len(reservations) + len(confirmations) == len(verrous)
    for groupe in (reservations, confirmations):
        assert {a.chemin for a in groupe} == {f"/api/v1/seats/{p}/lock" for p in places}
        assert len(groupe) == 2
        for appel in groupe:
            assert appel.corps["seance_id"] == str(seance.id)
            assert appel.corps["commande_id"] == commande_id
    # Ordre : toutes les réservations, puis toutes les confirmations, puis un seul paiement.
    indices = {id(a): i for i, a in enumerate(sortants)}
    assert max(indices[id(a)] for a in reservations) < min(indices[id(a)] for a in confirmations)
    paiements = [a for a in sortants if a.cible == "paiements"]
    assert [(a.methode, a.chemin) for a in paiements] == [("POST", "/api/v1/payments")]
    assert indices[id(paiements[0])] > max(indices[id(a)] for a in confirmations)
    # Jeton de service sur chaque appel sortant.
    assert keycloak.jetons_emis
    jetons_service = {f"Bearer {jeton}" for jeton in keycloak.jetons_emis}
    for appel in sortants:
        assert appel.entetes.get("authorization") in jetons_service, appel


async def test_une_place_verrouillee_par_une_autre_commande_renvoie_409_et_expire_la_commande(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    billets: Any,
    depot: Any,
    journal: Any,
) -> None:
    billets.semer_verrou(seance["C1"], uuid4())

    reponse = await client.post(ORDERS, json=seance.corps("A1", "C1"), headers=entetes_a)

    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["code"] == "SEAT_ALREADY_TAKEN"
    commandes = depot.commandes_de("client-a")
    assert [c.statut for c in commandes] == [StatutCommande.EXPIREE]
    assert journal.de("paiements") == []


async def test_commandes_envoie_l_identifiant_de_commande_comme_idempotency_key(
    client: httpx.AsyncClient, seance: Any, entetes_a: dict[str, str], journal: Any
) -> None:
    reponse = await client.post(ORDERS, json=seance.corps("A1", "C1"), headers=entetes_a)

    assert reponse.status_code == 201, reponse.text
    commande = reponse.json()
    paiements = journal.de("paiements")
    assert len(paiements) >= 1
    for appel in paiements:
        assert appel.entetes.get("idempotency-key") == commande["id"]
        assert appel.corps["commande_id"] == commande["id"]
        assert appel.corps["seance_id"] == str(seance.id)
        assert appel.corps["montant"] == commande["montant_total"]


async def test_seul_commandes_appelle_paiements(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    journal: Any,
    keycloak: Any,
) -> None:
    reponse = await client.post(ORDERS, json=seance.corps("A1"), headers=entetes_a)

    assert reponse.status_code == 201, reponse.text
    paiements = journal.de("paiements")
    assert [(a.methode, a.chemin) for a in paiements] == [("POST", "/api/v1/payments")]
    # Émis par Commandes, avec le jeton du client services (et non celui de l'acheteur).
    assert paiements[0].entetes["authorization"] != entetes_a["Authorization"]
    assert paiements[0].entetes["authorization"] in {f"Bearer {j}" for j in keycloak.jetons_emis}


# --- E5 : séance et validation -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("situation", "statut", "code"),
    [
        ("inconnue", 404, "SHOW_NOT_FOUND"),
        ("annulee", 409, "SHOW_CANCELLED"),
        ("commencee", 409, "SHOW_ALREADY_STARTED"),
    ],
)
async def test_une_seance_inconnue_annulee_ou_commencee_est_refusee_sans_commande(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    catalogue: Any,
    horloge: Any,
    depot: Any,
    journal: Any,
    situation: str,
    statut: int,
    code: str,
) -> None:
    if situation == "inconnue":
        del catalogue.seances[seance.id]
    elif situation == "annulee":
        catalogue.seances[seance.id]["annulee"] = True
    else:
        debut = horloge.maintenant - timedelta(hours=1)
        catalogue.seances[seance.id]["debut"] = debut.isoformat()

    reponse = await client.post(ORDERS, json=seance.corps("A1"), headers=entetes_a)

    assert reponse.status_code == statut, reponse.text
    assert reponse.json()["code"] == code
    assert depot.commandes_de("client-a") == []
    assert journal.de("billets") == []
    assert journal.de("paiements") == []


async def test_une_place_inconnue_renvoie_404_seat_not_found(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    depot: Any,
    journal: Any,
) -> None:
    corps = seance.corps("A1")
    corps["place_ids"].append(str(uuid4()))

    reponse = await client.post(ORDERS, json=corps, headers=entetes_a)

    assert reponse.status_code == 404, reponse.text
    assert reponse.json()["code"] == "SEAT_NOT_FOUND"
    commandes = depot.commandes_de("client-a")
    assert [c.statut for c in commandes] == [StatutCommande.EXPIREE]
    assert journal.de("paiements") == []
    expirees = depot.evenements_de(EVENEMENT_COMMANDE_EXPIREE)
    assert len(expirees) == 1
    assert set(expirees[0].data["place_ids"]) == set(corps["place_ids"])


def _corps_invalide(seance: Any, cas: str) -> dict[str, Any]:
    corps = seance.corps("A1")
    if cas == "places_vides":
        corps["place_ids"] = []
    elif cas == "onze_places":
        corps["place_ids"] = [str(uuid4()) for _ in range(11)]
    elif cas == "doublon":
        corps["place_ids"] = [str(seance["A1"]), str(seance["A1"])]
    elif cas == "seance_non_uuid":
        corps["seance_id"] = "pas-un-uuid"
    elif cas == "carte_15_chiffres":
        corps["carte_test"] = "424242424242424"
    else:
        del corps["carte_test"]
    return corps


@pytest.mark.parametrize(
    ("cas", "champ"),
    [
        ("places_vides", "place_ids"),
        ("onze_places", "place_ids"),
        ("doublon", "place_ids"),
        ("seance_non_uuid", "seance_id"),
        ("carte_15_chiffres", "carte_test"),
        ("sans_carte", "carte_test"),
    ],
)
async def test_un_corps_de_commande_invalide_renvoie_422(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    depot: Any,
    journal: Any,
    cas: str,
    champ: str,
) -> None:
    reponse = await client.post(ORDERS, json=_corps_invalide(seance, cas), headers=entetes_a)

    assert reponse.status_code == 422, reponse.text
    probleme = reponse.json()
    assert probleme["code"] == "REQUETE_INVALIDE"
    assert any(champ in erreur["champ"] for erreur in probleme["erreurs"]), probleme
    assert depot.commandes_de("client-a") == []
    assert journal.appels == []
