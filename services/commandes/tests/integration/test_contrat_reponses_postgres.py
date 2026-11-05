"""E10 (BIL-008) : les réponses réelles (vraie base, vrais Billets et Paiements) valident les
schémas des contrats : `Commande`, `CommandePage`, `Paiement` et `Probleme` (402, 404, 409,
422).
"""

import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.anyio


async def test_les_reponses_reelles_valident_le_schema_du_contrat(
    plateforme: Any, outils: Any
) -> None:
    creee = await plateforme.commander("A", ["A1"])
    commande = outils.exiger_statut(creee, 201, "creerCommande")
    assert outils.erreurs_schema(commande, "commandes", "Commande") == []

    page = outils.exiger_statut(await plateforme.lister("A"), 200, "listerCommandes")
    assert outils.erreurs_schema(page, "commandes", "CommandePage") == []

    commande_id = str(uuid.uuid4())
    paiement = await plateforme.paiements.post(
        outils.route_paiements,
        json={
            "commande_id": commande_id,
            "seance_id": str(plateforme.seance.id),
            "montant": 4500,
            "carte_test": outils.carte_acceptee,
        },
        headers={"Idempotency-Key": commande_id},
    )
    corps_paiement = outils.exiger_statut(paiement, 201, "creerPaiement")
    assert outils.erreurs_schema(corps_paiement, "paiements", "Paiement") == []

    problemes = {
        402: (
            await plateforme.commander("B", ["A2"], carte=outils.carte_refusee),
            "PAYMENT_REFUSED",
        ),
        404: (await plateforme.lire("A", str(uuid.uuid4())), "ORDER_NOT_FOUND"),
        409: (await plateforme.commander("B", ["A1"]), "SEAT_ALREADY_TAKEN"),
        422: (
            await plateforme.commandes_1.post(
                outils.route_commandes,
                json={"seance_id": "pas-un-uuid", "place_ids": [], "carte_test": "1"},
                headers=plateforme.entetes("A"),
            ),
            "REQUETE_INVALIDE",
        ),
    }
    for statut, (reponse, code) in problemes.items():
        corps = outils.exiger_probleme(reponse, statut, code, f"Probleme {statut}")
        assert outils.erreurs_schema(corps, "commandes", "Probleme") == [], statut
