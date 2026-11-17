"""Concurrence sur une même commande (review BIL-008, points 1, 2 et 5).

Les transitions de statut sont gardées (`WHERE statut = 'EN_ATTENTE'` ou `FOR UPDATE`) : jamais
de commande CONFIRMEE dont les places ont été libérées par un `ticketing.order.expired`, jamais
de second `ticketing.order.confirmed`. `payerCommande` sur une réservation encore en cours
(`expire_le` NULL) : 409 REQUEST_IN_PROGRESS, sans appel à Paiements.

L'entrelacement est forcé par la gateway de test : un appel `verrouillerPlace` choisi est retenu
jusqu'à ce que la requête concurrente ait fini, puis relâché. Vrais Billets (vrai Redis) et
Paiements, deux instances de Commandes sur la même base.
"""

import asyncio
import json
from typing import Any

import httpx
import pytest

from commandes.infra.clients import CIBLE_BILLETS, CIBLE_PAIEMENTS

pytestmark = [pytest.mark.anyio, pytest.mark.concurrence]

CONFIRMEE = "ticketing.order.confirmed"
EXPIREE = "ticketing.order.expired"


def _retenir_verrou(
    plateforme: Any,
    *,
    confirmation: bool,
    rang: int,
    liberation: asyncio.Event,
    arrivee: asyncio.Event,
) -> None:
    """Retient le `rang`-ième appel (0 : le premier) de `verrouillerPlace` dont le corps porte
    `confirmation` ; `arrivee` signale qu'il est retenu, `liberation` le relâche."""
    vus = 0

    async def retenir(requete: httpx.Request, transport: httpx.AsyncBaseTransport) -> Any:
        nonlocal vus
        corps = json.loads(requete.content or b"{}")
        if corps.get("confirmation") is confirmation:
            numero = vus
            vus += 1
            if numero == rang:
                arrivee.set()
                await liberation.wait()
        return await transport.handle_async_request(requete)

    plateforme.gateway.intercepteurs[CIBLE_BILLETS] = retenir


async def _commande_en_attente(plateforme: Any) -> str:
    (commande,) = await plateforme.bases.commandes_de("client-a")
    assert commande["statut"] == "EN_ATTENTE", commande
    return str(commande["id"])


async def test_payer_pendant_la_reservation_ne_confirme_jamais_une_commande_expiree(
    plateforme: Any, outils: Any
) -> None:
    liberation, arrivee = asyncio.Event(), asyncio.Event()
    _retenir_verrou(plateforme, confirmation=False, rang=0, liberation=liberation, arrivee=arrivee)
    creation = asyncio.create_task(plateforme.commander("A", ["A1"]))
    await outils.borne("verrou de réservation retenu", arrivee.wait())
    commande_id = await _commande_en_attente(plateforme)

    await plateforme.payer("A", commande_id, instance=plateforme.commandes_2)
    liberation.set()
    await outils.borne("creerCommande relâchée", creation)

    statut = (await plateforme.bases.commande(commande_id))["statut"]
    expirees = await plateforme.bases.evenements_de(EXPIREE, commande_id)
    confirmees = await plateforme.bases.evenements_de(CONFIRMEE, commande_id)
    assert len(confirmees) <= 1, confirmees
    assert not (expirees and statut == "CONFIRMEE"), (
        f"commande CONFIRMEE alors qu'un order.expired a libéré ses places : {expirees}"
    )
    assert not (expirees and confirmees), (
        f"order.confirmed publié pour une commande expirée : {expirees} puis {confirmees}"
    )


async def test_payer_pendant_la_reservation_renvoie_409_request_in_progress_sans_appeler_paiements(
    plateforme: Any, outils: Any
) -> None:
    liberation, arrivee = asyncio.Event(), asyncio.Event()
    _retenir_verrou(plateforme, confirmation=False, rang=0, liberation=liberation, arrivee=arrivee)
    creation = asyncio.create_task(plateforme.commander("A", ["A1"]))
    await outils.borne("verrou de réservation retenu", arrivee.wait())
    commande_id = await _commande_en_attente(plateforme)

    reponse = await plateforme.payer("A", commande_id, instance=plateforme.commandes_2)
    appels_paiements = len(plateforme.gateway.appels_vers(CIBLE_PAIEMENTS))
    liberation.set()
    creee = await outils.borne("creerCommande relâchée", creation)

    outils.exiger_probleme(
        reponse, 409, "REQUEST_IN_PROGRESS", "payerCommande pendant la réservation"
    )
    assert appels_paiements == 0, "payerCommande a appelé Paiements pendant la réservation"
    corps = outils.exiger_statut(creee, 201, "creerCommande après le refus de payerCommande")
    assert corps["statut"] == "CONFIRMEE"
    assert (await plateforme.bases.commande(commande_id))["statut"] == "CONFIRMEE"
    assert await plateforme.bases.evenements_de(EXPIREE, commande_id) == []


async def test_payer_pendant_le_reverrouillage_de_creer_commande_ne_publie_qu_un_order_confirmed(
    plateforme: Any, outils: Any
) -> None:
    liberation, arrivee = asyncio.Event(), asyncio.Event()
    # Premier reverrouillage (confirmation: true) : celui de creerCommande.
    _retenir_verrou(plateforme, confirmation=True, rang=0, liberation=liberation, arrivee=arrivee)
    creation = asyncio.create_task(plateforme.commander("A", ["A1"]))
    await outils.borne("reverrouillage de creerCommande retenu", arrivee.wait())
    commande_id = await _commande_en_attente(plateforme)

    paiement = await plateforme.payer("A", commande_id, instance=plateforme.commandes_2)
    liberation.set()
    creee = await outils.borne("creerCommande relâchée", creation)

    assert outils.exiger_statut(paiement, 200, "payerCommande concurrent")["statut"] == "CONFIRMEE"
    assert creee.status_code < 500, creee.text
    assert (await plateforme.bases.commande(commande_id))["statut"] == "CONFIRMEE"
    confirmees = await plateforme.bases.evenements_de(CONFIRMEE, commande_id)
    assert len(confirmees) == 1, f"{len(confirmees)} order.confirmed : {confirmees}"
    assert await plateforme.bases.evenements_de(EXPIREE, commande_id) == []
    assert len(await plateforme.bases.paiements_de(commande_id)) == 1


async def test_deux_payer_commande_simultanes_ne_publient_qu_un_order_confirmed(
    plateforme: Any, outils: Any
) -> None:
    # Commande EN_ATTENTE, réservation terminée, aucun paiement (Paiements injoignable).
    plateforme.paiements_injoignable()
    reponse = await plateforme.commander("A", ["A1"])
    outils.exiger_probleme(
        reponse, 503, "SERVICE_INDISPONIBLE", "creerCommande, Paiements en panne"
    )
    commande_id = await _commande_en_attente(plateforme)
    plateforme.retablir()

    liberation, arrivee = asyncio.Event(), asyncio.Event()
    # Le second payerCommande lit la commande EN_ATTENTE puis reste au reverrouillage pendant
    # que le premier la confirme.
    _retenir_verrou(plateforme, confirmation=True, rang=0, liberation=liberation, arrivee=arrivee)
    second = asyncio.create_task(
        plateforme.payer("A", commande_id, instance=plateforme.commandes_2)
    )
    await outils.borne("reverrouillage du second payerCommande retenu", arrivee.wait())
    premier = await plateforme.payer("A", commande_id, instance=plateforme.commandes_1)
    liberation.set()
    reponse_second = await outils.borne("second payerCommande relâché", second)

    assert outils.exiger_statut(premier, 200, "premier payerCommande")["statut"] == "CONFIRMEE"
    assert reponse_second.status_code in (200, 409), reponse_second.text
    if reponse_second.status_code == 409:
        assert reponse_second.json()["code"] == "ORDER_NOT_PENDING", reponse_second.text
    assert (await plateforme.bases.commande(commande_id))["statut"] == "CONFIRMEE"
    confirmees = await plateforme.bases.evenements_de(CONFIRMEE, commande_id)
    assert len(confirmees) == 1, f"{len(confirmees)} order.confirmed : {confirmees}"
    assert len(await plateforme.bases.paiements_de(commande_id)) == 1
