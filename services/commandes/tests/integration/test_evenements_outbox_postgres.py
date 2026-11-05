"""CA3 et E1 (BIL-008, décisions Q2, Q8, Q19, Q22) : `ticketing.order.confirmed` et
`ticketing.order.expired` rangés dans l'outbox de Commandes, dans la même transaction que le
changement de statut (même `xmin` PostgreSQL), et conformes à leur schéma JSON.
"""

from typing import Any

import pytest

pytestmark = pytest.mark.anyio

CONFIRMEE = "ticketing.order.confirmed"
EXPIREE = "ticketing.order.expired"


async def _seule_commande(plateforme: Any, sujet: str = "client-a") -> dict[str, Any]:
    commandes = await plateforme.bases.commandes_de(sujet)
    assert len(commandes) == 1, commandes
    return commandes[0]


# --- CA3 ---------------------------------------------------------------------------------------


async def test_la_confirmation_et_order_confirmed_sont_ecrits_dans_la_meme_transaction(
    plateforme: Any, outils: Any
) -> None:
    reponse = await plateforme.commander("A", ["A1"])

    corps = outils.exiger_statut(reponse, 201, "A commande A1")
    commande = await plateforme.bases.commande(corps["id"])
    assert commande["statut"] == "CONFIRMEE"
    evenements = await plateforme.bases.evenements_de(CONFIRMEE, corps["id"])
    assert len(evenements) == 1, evenements
    assert evenements[0]["xmin"] == await plateforme.bases.xmin_commande(corps["id"])


async def test_order_confirmed_respecte_son_schema(plateforme: Any, outils: Any) -> None:
    reponse = await plateforme.commander("A", ["A1", "C1"], correlation="correlation-bil-008-1")

    corps = outils.exiger_statut(reponse, 201, "A commande A1 et C1")
    (evenement,) = await plateforme.bases.evenements_de(CONFIRMEE, corps["id"])
    assert outils.erreurs_evenement(evenement) == []
    data = evenement["data"]
    assert data["commande_id"] == corps["id"]
    assert data["client"] == "client-a"
    assert data["email"] == "client.test@exemple.test"
    assert data["seance_id"] == str(plateforme.seance.id)
    assert sorted((ligne["place_id"], ligne["montant"]) for ligne in data["lignes"]) == sorted(
        (str(plateforme.seance.places[p]), plateforme.seance.prix[p]) for p in ("A1", "C1")
    )
    assert data["montant_total"] == 7500
    assert evenement["correlation_id"] == "correlation-bil-008-1"


async def test_un_revendeur_publie_order_confirmed_avec_un_email_nul(
    plateforme: Any, outils: Any
) -> None:
    reponse = await plateforme.commander("R1", ["A1"])

    corps = outils.exiger_statut(reponse, 201, "R1 commande A1")
    (evenement,) = await plateforme.bases.evenements_de(CONFIRMEE, corps["id"])
    assert outils.erreurs_evenement(evenement) == []
    assert evenement["data"]["email"] is None
    assert evenement["data"]["client"] == outils.clients["R1"]["sujet"]


@pytest.mark.parametrize("echec", ["carte_refusee", "place_prise", "paiements_en_panne"])
async def test_aucun_order_confirmed_sans_paiement_accepte(
    echec: str, plateforme: Any, outils: Any
) -> None:
    carte = outils.carte_acceptee
    attendu = {"carte_refusee": 402, "place_prise": 409, "paiements_en_panne": 503}[echec]
    if echec == "carte_refusee":
        carte = outils.carte_refusee
    elif echec == "place_prise":
        await plateforme.verrouiller_pour_autrui("A1")
    else:
        plateforme.paiements_injoignable()

    reponse = await plateforme.commander("A", ["A1"], carte=carte)

    outils.exiger_statut(reponse, attendu, echec)
    await _seule_commande(plateforme)
    assert await plateforme.bases.outbox(CONFIRMEE) == []


async def test_un_rejeu_ne_publie_qu_un_seul_order_confirmed(plateforme: Any, outils: Any) -> None:
    plateforme.paiements_injoignable()
    premiere = await plateforme.commander("A", ["A1"], cle="cle-bil-008-rejeu")
    outils.exiger_probleme(premiere, 503, "SERVICE_INDISPONIBLE", "Paiements en panne")
    commande = await _seule_commande(plateforme)

    plateforme.retablir()
    payee = await plateforme.payer("A", str(commande["id"]))
    outils.exiger_statut(payee, 200, "payerCommande après 503")
    rejeu = await plateforme.commander("A", ["A1"], cle="cle-bil-008-rejeu")
    outils.exiger_statut(rejeu, 200, "rejeu de creerCommande, même clé")

    assert len(await plateforme.bases.evenements_de(CONFIRMEE, str(commande["id"]))) == 1


# --- E1 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "echec", ["verrou_refuse", "place_perdue_au_reverrouillage", "carte_refusee"]
)
async def test_chaque_echec_synchrone_expire_la_commande_et_publie_order_expired(
    echec: str, plateforme: Any, outils: Any
) -> None:
    carte = outils.carte_acceptee
    attendu = 409
    if echec == "verrou_refuse":
        await plateforme.verrouiller_pour_autrui("C1")
    elif echec == "place_perdue_au_reverrouillage":
        plateforme.perdre_place_au_reverrouillage("C1")
    else:
        carte, attendu = outils.carte_refusee, 402

    reponse = await plateforme.commander("A", ["A1", "C1"], carte=carte)

    outils.exiger_statut(reponse, attendu, echec)
    commande = await _seule_commande(plateforme)
    assert commande["statut"] == "EXPIREE"
    evenements = await plateforme.bases.evenements_de(EXPIREE, str(commande["id"]))
    assert len(evenements) == 1, evenements
    evenement = evenements[0]
    assert evenement["xmin"] == await plateforme.bases.xmin_commande(str(commande["id"]))
    assert outils.erreurs_evenement(evenement) == []
    assert evenement["data"]["seance_id"] == str(plateforme.seance.id)
    assert sorted(evenement["data"]["place_ids"]) == sorted(plateforme.seance.ids("A1", "C1"))


async def test_un_paiement_refuse_renvoie_402_et_expire_la_commande(
    plateforme: Any, outils: Any
) -> None:
    reponse = await plateforme.commander("A", ["A1"], carte=outils.carte_refusee)

    outils.exiger_probleme(reponse, 402, "PAYMENT_REFUSED", "carte refusée")
    commande = await _seule_commande(plateforme)
    assert commande["statut"] == "EXPIREE"
    paiements = await plateforme.bases.paiements_de(commande["id"])
    assert [p["statut"] for p in paiements] == ["REFUSE"]


@pytest.mark.parametrize("issue", ["succes", "paiements_en_panne"])
async def test_aucun_order_expired_pour_une_commande_confirmee_ou_en_attente(
    issue: str, plateforme: Any, outils: Any
) -> None:
    if issue == "paiements_en_panne":
        plateforme.paiements_injoignable()

    reponse = await plateforme.commander("A", ["A1"])

    outils.exiger_statut(reponse, 201 if issue == "succes" else 503, issue)
    commande = await _seule_commande(plateforme)
    assert commande["statut"] == ("CONFIRMEE" if issue == "succes" else "EN_ATTENTE")
    assert await plateforme.bases.outbox(EXPIREE) == []
