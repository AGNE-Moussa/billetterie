"""E4, E5 et E8 (BIL-008, décisions Q4, Q11, Q22, `securite.md`) : la commande appartient au
sujet du jeton, la carte n'est ni journalisée ni enregistrée, et les appels vers Billets et
Paiements portent le jeton de service et la corrélation de la requête.
"""

import logging
from typing import Any

import jwt
import pytest

pytestmark = pytest.mark.anyio


async def test_la_commande_appartient_au_sujet_du_jeton(plateforme: Any, outils: Any) -> None:
    client = await plateforme.commander("A", ["A1"])
    revendeur = await plateforme.commander("R1", ["A2"])

    commande_a = await plateforme.bases.commande(outils.exiger_statut(client, 201, "A")["id"])
    commande_r1 = await plateforme.bases.commande(outils.exiger_statut(revendeur, 201, "R1")["id"])
    assert commande_a["client"] == "client-a"
    assert commande_a["email"] == "client.test@exemple.test"
    assert commande_r1["client"] == outils.clients["R1"]["sujet"]
    assert commande_r1["email"] is None
    assert await plateforme.bases.commandes.contient_texte(outils.carte_acceptee) == []


async def test_la_carte_n_est_ni_journalisee_ni_enregistree(
    plateforme: Any, outils: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    acceptee = await plateforme.commander("A", ["A1"], carte=outils.carte_acceptee)
    refusee = await plateforme.commander("B", ["A2"], carte=outils.carte_refusee)

    outils.exiger_statut(acceptee, 201, "carte acceptée")
    outils.exiger_statut(refusee, 402, "carte refusée")
    journaux = "\n".join(
        f"{r.name} {r.getMessage()} {r.exc_text or ''} {vars(r)}" for r in caplog.records
    )
    for carte in (outils.carte_acceptee, outils.carte_refusee):
        assert carte not in journaux
        assert await plateforme.bases.commandes.contient_texte(carte) == []
        assert await plateforme.bases.paiements.contient_texte(carte) == []
    assert plateforme.jetons_emis, "aucun jeton émis pendant le parcours"
    for jeton in plateforme.jetons_emis:
        assert jeton not in journaux


async def test_les_appels_portent_le_jeton_de_service_et_la_correlation(
    plateforme: Any, outils: Any
) -> None:
    reponse = await plateforme.commander("A", ["A1"], correlation="correlation-bil-008-2")

    outils.exiger_statut(reponse, 201, "A commande A1")
    for cible in ("billets", "paiements"):
        appels = plateforme.gateway.appels_vers(cible)
        assert appels, f"aucun appel vers {cible}"
        for appel in appels:
            assert appel.entetes.get("x-correlation-id") == "correlation-bil-008-2", appel
            schema, _, jeton = appel.entetes.get("authorization", "").partition(" ")
            assert schema == "Bearer", appel
            claims = jwt.decode(jeton, options={"verify_signature": False})
            assert claims["azp"] == "services", claims
            assert {"seats:lock", "payments:write"} <= set(claims["scope"].split()), claims
