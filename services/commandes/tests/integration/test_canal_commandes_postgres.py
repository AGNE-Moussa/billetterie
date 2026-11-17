"""Étape « Rattacher chaque commande à son canal » de BIL-012 (décision Q3, H7) : canal DIRECT ou
PARTENAIRE déduit du rôle du jeton, enregistré en base seulement (colonne `canal` de la
migration 0005), jamais exposé dans l'API ni dans les événements.

Vraie base PostgreSQL, vrai Redis, vrais Billets et Paiements (conftest du service) ; commandes
créées par l'API.
"""

from typing import Any

import pytest

pytestmark = pytest.mark.anyio

CONFIRMEE = "ticketing.order.confirmed"
TOURS_CONCURRENCE = 10
CANAL_ATTENDU = {"R1": "PARTENAIRE", "A": "DIRECT"}


def _canal(ligne: dict[str, Any]) -> Any:
    assert "canal" in ligne, f"colonne canal absente de commandes (migration 0005) : {ligne}"
    return ligne["canal"]


async def test_une_commande_partenaire_creee_par_l_api_est_enregistree_canal_partenaire_avec_email_nul(  # noqa: E501
    plateforme: Any, outils: Any
) -> None:
    reponse = await plateforme.commander("R1", ["A1"], carte=outils.carte_acceptee)

    corps = outils.exiger_statut(reponse, 201, "R1 commande A1")
    assert corps["statut"] == "CONFIRMEE"
    assert corps["montant_total"] == 4500
    ligne = await plateforme.bases.commande(corps["id"])
    assert _canal(ligne) == "PARTENAIRE"
    assert ligne["email"] is None
    (evenement,) = await plateforme.bases.evenements_de(CONFIRMEE, corps["id"])
    assert evenement["data"]["email"] is None


async def test_une_commande_client_direct_est_enregistree_canal_direct_avec_son_email(
    plateforme: Any, outils: Any
) -> None:
    reponse = await plateforme.commander("A", ["A2"])

    corps = outils.exiger_statut(reponse, 201, "A commande A2")
    ligne = await plateforme.bases.commande(corps["id"])
    assert _canal(ligne) == "DIRECT"
    assert ligne["email"] == "client.test@exemple.test"


async def test_un_revendeur_paie_sa_commande_en_attente_apres_un_503_de_paiements(
    plateforme: Any, outils: Any
) -> None:
    plateforme.paiements_injoignable()
    premiere = await plateforme.commander("R1", ["A3"])
    outils.exiger_probleme(premiere, 503, "SERVICE_INDISPONIBLE", "R1 commande, Paiements en panne")
    (en_attente,) = await plateforme.bases.commandes_de(outils.clients["R1"]["sujet"])
    assert en_attente["statut"] == "EN_ATTENTE", en_attente
    plateforme.retablir()

    reponse = await plateforme.payer("R1", str(en_attente["id"]), carte=outils.carte_acceptee)

    corps = outils.exiger_statut(reponse, 200, "R1 paie après le 503")
    assert corps["statut"] == "CONFIRMEE"
    ligne = await plateforme.bases.commande(corps["id"])
    assert _canal(ligne) == "PARTENAIRE"
    assert ligne["email"] is None
    evenements = await plateforme.bases.evenements_de(CONFIRMEE, corps["id"])
    assert len(evenements) == 1, evenements
    assert evenements[0]["data"]["email"] is None


@pytest.mark.concurrence
async def test_un_revendeur_et_un_client_direct_en_parallele_sur_la_meme_place_une_seule_vente_au_canal_du_gagnant(  # noqa: E501
    plateforme: Any, outils: Any
) -> None:
    appelants = ("R1", "A")
    for tour in range(TOURS_CONCURRENCE):
        # Nouvelle séance à chaque tour : ni place ni plafond hérités du tour précédent.
        seance = await plateforme.nouvelle_seance()

        async def appel(numero: int, seance: Any = seance) -> Any:
            return await plateforme.commander(
                appelants[numero], ["A1"], seance=seance, instance=plateforme.instance(numero)
            )

        reponses = await outils.barriere(2, appel)

        assert sorted(r.status_code for r in reponses) == [201, 409], (
            tour,
            [r.text for r in reponses],
        )
        for qui, reponse in zip(appelants, reponses, strict=True):
            (ligne,) = await plateforme.bases.commandes.lignes(
                "SELECT * FROM commandes WHERE seance_id = :s AND client = :c",
                s=seance.id,
                c=outils.clients[qui]["sujet"],
            )
            if reponse.status_code == 201:
                assert reponse.json()["statut"] == "CONFIRMEE", (tour, reponse.text)
                assert ligne["statut"] == "CONFIRMEE", (tour, ligne)
            else:
                assert reponse.json()["code"] == "SEAT_ALREADY_TAKEN", (tour, reponse.text)
                assert ligne["statut"] == "EXPIREE", (tour, ligne)
            assert _canal(ligne) == CANAL_ATTENDU[qui], (tour, qui, ligne)
        contenant = await plateforme.bases.commandes.lignes(
            "SELECT c.statut FROM commandes c JOIN lignes_commande l ON l.commande_id = c.id"
            " WHERE l.place_id = :place",
            place=seance.places["A1"],
        )
        assert [c["statut"] for c in contenant].count("CONFIRMEE") == 1, (tour, contenant)
