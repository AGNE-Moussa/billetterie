"""creerPaiement : paiement simulé, idempotent par commande (CA2 et E4 du plan BIL-008 ;
décisions Q4, Q5, Q6, Q12)."""

from typing import Any
from uuid import uuid4

import httpx
import pytest

from paiements.domaine.paiements import StatutPaiement

pytestmark = pytest.mark.anyio

PAYMENTS = "/api/v1/payments"
CARTE_REFUSEE = "4000000000000002"
CARTE_ACCEPTEE = "4242424242424242"


async def test_un_paiement_accepte_renvoie_201_accepte(
    client: httpx.AsyncClient,
    entetes_service: dict[str, str],
    requete_paiement: Any,
    depot: Any,
) -> None:
    corps, cle = requete_paiement(montant=4500)

    reponse = await client.post(PAYMENTS, json=corps, headers={**entetes_service, **cle})

    assert reponse.status_code == 201, reponse.text
    paiement = reponse.json()
    assert paiement["statut"] == "ACCEPTE"
    assert paiement["montant"] == 4500
    assert paiement["commande_id"] == corps["commande_id"]
    assert paiement["seance_id"] == corps["seance_id"]
    assert len(depot.paiements) == 1


async def test_rejouer_le_meme_paiement_renvoie_le_paiement_enregistre(
    client: httpx.AsyncClient,
    entetes_service: dict[str, str],
    requete_paiement: Any,
    depot: Any,
) -> None:
    corps, cle = requete_paiement()
    entetes = {**entetes_service, **cle}

    premiere = await client.post(PAYMENTS, json=corps, headers=entetes)
    seconde = await client.post(PAYMENTS, json=corps, headers=entetes)

    assert premiere.status_code == 201, premiere.text
    assert seconde.status_code == 201, seconde.text
    assert premiere.json()["id"] == seconde.json()["id"]
    assert len(depot.paiements) == 1


async def test_rejouer_un_paiement_refuse_renvoie_encore_402(
    client: httpx.AsyncClient,
    entetes_service: dict[str, str],
    requete_paiement: Any,
    depot: Any,
) -> None:
    corps, cle = requete_paiement(carte=CARTE_REFUSEE)
    entetes = {**entetes_service, **cle}

    reponses = [await client.post(PAYMENTS, json=corps, headers=entetes) for _ in range(2)]

    assert [r.status_code for r in reponses] == [402, 402], [r.text for r in reponses]
    assert [r.json()["code"] for r in reponses] == ["PAYMENT_REFUSED"] * 2
    assert [p.statut for p in depot.paiements.values()] == [StatutPaiement.REFUSE]


async def test_rejouer_avec_une_autre_carte_renvoie_le_resultat_enregistre(
    client: httpx.AsyncClient,
    entetes_service: dict[str, str],
    requete_paiement: Any,
    depot: Any,
) -> None:
    commande_id, seance_id = uuid4(), uuid4()
    refus, cle = requete_paiement(commande_id=commande_id, seance_id=seance_id, carte=CARTE_REFUSEE)
    autre, _ = requete_paiement(commande_id=commande_id, seance_id=seance_id, carte=CARTE_ACCEPTEE)
    entetes = {**entetes_service, **cle}

    premiere = await client.post(PAYMENTS, json=refus, headers=entetes)
    seconde = await client.post(PAYMENTS, json=autre, headers=entetes)

    assert premiere.status_code == 402, premiere.text
    assert seconde.status_code == 402, seconde.text
    assert seconde.json()["code"] == "PAYMENT_REFUSED"
    assert [p.statut for p in depot.paiements.values()] == [StatutPaiement.REFUSE]


@pytest.mark.parametrize("change", ["montant", "seance_id"])
async def test_un_autre_montant_ou_une_autre_seance_pour_la_meme_commande_renvoie_409(
    client: httpx.AsyncClient,
    entetes_service: dict[str, str],
    requete_paiement: Any,
    depot: Any,
    change: str,
) -> None:
    corps, cle = requete_paiement(montant=4500)
    entetes = {**entetes_service, **cle}
    autre = (
        {**corps, "montant": 4600} if change == "montant" else {**corps, "seance_id": str(uuid4())}
    )

    premiere = await client.post(PAYMENTS, json=corps, headers=entetes)
    seconde = await client.post(PAYMENTS, json=autre, headers=entetes)

    assert premiere.status_code == 201, premiere.text
    assert seconde.status_code == 409, seconde.text
    assert seconde.json()["code"] == "PAYMENT_ALREADY_EXISTS"
    assert len(depot.paiements) == 1
    origine = next(iter(depot.paiements.values()))
    assert str(origine.id) == premiere.json()["id"]
    assert (origine.montant, str(origine.seance_id)) == (4500, corps["seance_id"])
    assert origine.statut is StatutPaiement.ACCEPTE


@pytest.mark.parametrize("cle", ["absente", "pas-un-uuid", "autre_uuid"])
async def test_l_idempotency_key_de_paiements_est_obligatoire_et_egale_a_commande_id(
    client: httpx.AsyncClient,
    entetes_service: dict[str, str],
    requete_paiement: Any,
    depot: Any,
    cle: str,
) -> None:
    corps, _ = requete_paiement()
    entetes = dict(entetes_service)
    if cle == "pas-un-uuid":
        entetes["Idempotency-Key"] = "pas-un-uuid"
    elif cle == "autre_uuid":
        entetes["Idempotency-Key"] = str(uuid4())

    reponse = await client.post(PAYMENTS, json=corps, headers=entetes)

    assert reponse.status_code == 422, reponse.text
    assert reponse.json()["code"] == "REQUETE_INVALIDE"
    assert depot.paiements == {}


@pytest.mark.parametrize("appelant", ["client_a", "revendeur_r1", "services_sans_scope"])
async def test_paiements_est_reserve_au_scope_payments_write(
    client: httpx.AsyncClient,
    emetteur: Any,
    requete_paiement: Any,
    depot: Any,
    appelant: str,
) -> None:
    if appelant == "client_a":
        entetes = emetteur.entetes(
            sujet="client-a",
            roles=["customer"],
            scopes=["orders:read", "orders:write"],
            email="client.test@exemple.test",
        )
    elif appelant == "revendeur_r1":
        entetes = emetteur.entetes(
            roles=["partner"], scopes=["orders:read", "orders:write"], client="revendeur-test"
        )
    else:
        entetes = emetteur.entetes(client="services", scopes=["seats:lock"])
    corps, cle = requete_paiement()

    reponse = await client.post(PAYMENTS, json=corps, headers={**entetes, **cle})

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["code"] == "SCOPE_MANQUANT"
    assert depot.paiements == {}
