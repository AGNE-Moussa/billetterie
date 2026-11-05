"""lirePaiement : lecture seule du paiement d'une commande (review BIL-008, point 3).

Utilisée par Commandes avant d'expirer une commande déjà envoyée à Paiements ; ne crée jamais
de paiement et exige le scope payments:write.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest

from paiements.domaine.paiements import Paiement, StatutPaiement

pytestmark = pytest.mark.anyio

PAYMENTS = "/api/v1/payments"
CREE_LE = datetime(2026, 11, 3, 8, 55, tzinfo=UTC)


def _enregistrer(depot: Any, statut: StatutPaiement) -> Paiement:
    paiement = Paiement(
        id=uuid4(),
        commande_id=uuid4(),
        seance_id=uuid4(),
        montant=4500,
        statut=statut,
        cree_le=CREE_LE,
    )
    depot.paiements[paiement.commande_id] = paiement
    return paiement


@pytest.mark.parametrize("statut", list(StatutPaiement))
async def test_lire_un_paiement_enregistre_renvoie_200_quel_que_soit_son_statut(
    client: httpx.AsyncClient,
    entetes_service: dict[str, str],
    depot: Any,
    statut: StatutPaiement,
) -> None:
    paiement = _enregistrer(depot, statut)

    reponse = await client.get(f"{PAYMENTS}/{paiement.commande_id}", headers=entetes_service)

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["id"] == str(paiement.id)
    assert corps["commande_id"] == str(paiement.commande_id)
    assert corps["seance_id"] == str(paiement.seance_id)
    assert corps["montant"] == 4500
    assert corps["statut"] == statut.value
    assert datetime.fromisoformat(corps["cree_le"]) == CREE_LE
    assert list(depot.paiements.values()) == [paiement]


async def test_lire_le_paiement_d_une_commande_sans_paiement_renvoie_404_sans_en_creer(
    client: httpx.AsyncClient,
    entetes_service: dict[str, str],
    depot: Any,
) -> None:
    reponse = await client.get(f"{PAYMENTS}/{uuid4()}", headers=entetes_service)

    assert reponse.status_code == 404, reponse.text
    assert reponse.headers["content-type"].startswith("application/problem+json")
    assert reponse.json()["code"] == "PAYMENT_NOT_FOUND"
    assert depot.paiements == {}


async def test_lire_un_paiement_sans_jeton_renvoie_401(
    client: httpx.AsyncClient,
    depot: Any,
) -> None:
    paiement = _enregistrer(depot, StatutPaiement.ACCEPTE)

    reponse = await client.get(f"{PAYMENTS}/{paiement.commande_id}")

    assert reponse.status_code == 401, reponse.text
    assert reponse.json()["code"].startswith("JETON_")


@pytest.mark.parametrize("appelant", ["client_a", "revendeur_r1", "services_sans_scope"])
async def test_lire_un_paiement_est_reserve_au_scope_payments_write(
    client: httpx.AsyncClient,
    emetteur: Any,
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
    paiement = _enregistrer(depot, StatutPaiement.ACCEPTE)

    reponse = await client.get(f"{PAYMENTS}/{paiement.commande_id}", headers=entetes)

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["code"] == "SCOPE_MANQUANT"
    assert list(depot.paiements.values()) == [paiement]
