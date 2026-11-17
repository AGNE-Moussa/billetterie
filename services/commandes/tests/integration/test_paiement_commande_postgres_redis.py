"""CA2, E5 et E6 (BIL-008, décisions Q5, Q6, Q9, Q17) : paiement d'une commande par le vrai
Paiements, réponses perdues par la gateway de test (panne simulée).
"""

from typing import Any

import pytest

pytestmark = pytest.mark.anyio


async def _confirmations(plateforme: Any, commande_id: str) -> list[Any]:
    return await plateforme.bases.evenements_de("ticketing.order.confirmed", commande_id)


async def test_une_reponse_perdue_de_paiements_est_rejouee_sans_second_debit(
    plateforme: Any, outils: Any
) -> None:
    perdues = plateforme.perdre_reponses_paiements(1)

    reponse = await plateforme.commander("A", ["A1"])

    corps = outils.exiger_statut(reponse, 201, "commande, première réponse de Paiements perdue")
    assert corps["statut"] == "CONFIRMEE"
    assert len(perdues) == 1, perdues
    paiements = await plateforme.bases.paiements_de()
    assert [p["statut"] for p in paiements] == ["ACCEPTE"]
    assert len(await _confirmations(plateforme, corps["id"])) == 1


async def test_un_nouvel_essai_apres_delai_depasse_confirme_sans_second_debit(
    plateforme: Any, outils: Any
) -> None:
    perdues = plateforme.perdre_reponses_paiements()

    reponse = await plateforme.commander("A", ["A1", "C1"])

    outils.exiger_probleme(reponse, 503, "SERVICE_INDISPONIBLE", "3 réponses de Paiements perdues")
    assert len(perdues) == 3, perdues
    (commande,) = await plateforme.bases.commandes_de("client-a")
    assert commande["statut"] == "EN_ATTENTE"
    paiements_avant = await plateforme.bases.paiements_de()
    assert len(paiements_avant) == 1, paiements_avant

    plateforme.retablir()
    reponse = await plateforme.payer("A", str(commande["id"]))

    corps = outils.exiger_statut(reponse, 200, "payerCommande après 503")
    assert corps["statut"] == "CONFIRMEE"
    paiements = await plateforme.bases.paiements_de()
    assert len(paiements) == 1, paiements
    assert paiements[0]["id"] == paiements_avant[0]["id"]
    assert paiements[0]["montant"] == paiements_avant[0]["montant"] == corps["montant_total"]


async def test_le_refus_depend_de_la_carte_et_non_d_un_reglage_global(
    plateforme: Any, outils: Any
) -> None:
    demandes = (("A", ["A1"], outils.carte_refusee), ("B", ["A2"], outils.carte_acceptee))

    async def appel(numero: int) -> Any:
        qui, libelles, carte = demandes[numero]
        return await plateforme.commander(
            qui, libelles, carte=carte, instance=plateforme.instance(numero)
        )

    refusee, acceptee = await outils.barriere(2, appel)

    outils.exiger_probleme(refusee, 402, "PAYMENT_REFUSED", "carte refusée")
    assert outils.exiger_statut(acceptee, 201, "carte acceptée")["statut"] == "CONFIRMEE"


async def test_commandes_expire_la_commande_quand_paiements_signale_une_seance_annulee(
    plateforme: Any, outils: Any
) -> None:
    # Séance annulée pour Paiements seulement : le Catalogue la rend encore non annulée.
    await plateforme.bases.annuler_dans_paiements(plateforme.seance.id)

    reponse = await plateforme.commander("A", ["A1"])

    outils.exiger_probleme(reponse, 409, "SHOW_CANCELLED", "séance annulée pour Paiements")
    (commande,) = await plateforme.bases.commandes_de("client-a")
    assert commande["statut"] == "EXPIREE"
    expirees = await plateforme.bases.evenements_de("ticketing.order.expired", str(commande["id"]))
    assert len(expirees) == 1, expirees
    assert await plateforme.bases.paiements_de() == []
