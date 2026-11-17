"""CA1 et E1 (BIL-008, décisions Q2, Q8, Q18) : une place dont le verrou expire entre le 503 de
Paiements et le nouvel essai (`payerCommande`) est perdue : 409 SEAT_ALREADY_TAKEN, commande
EXPIREE, `ticketing.order.expired`, sans débit.

Durées courtes sur le vrai Billets (décision du coordinateur, 2026-11-03) : réservation **et**
confirmation à 2 s, pour une vraie expiration du verrou Redis. Le reverrouillage avant
Paiements se fait en durée de confirmation : seule la réduire rend l'expiration observable.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import anyio
import pytest

pytestmark = pytest.mark.anyio

DUREES_COURTES = {"duree_verrou_reservation": 2, "duree_verrou_confirmation": 2}
ATTENTE_EXPIRATION = 2.5


@pytest.fixture
async def plateforme_courte(
    plateforme_commandes: Callable[..., AbstractAsyncContextManager[Any]],
) -> AsyncIterator[Any]:
    async with plateforme_commandes(billets=DUREES_COURTES) as demarree:
        yield demarree


async def _commande_en_attente_apres_panne(plateforme: Any, outils: Any) -> str:
    """A commande A1, Paiements injoignable : 503 et commande EN_ATTENTE ; Paiements rétabli."""
    plateforme.paiements_injoignable()
    reponse = await plateforme.commander("A", ["A1"])
    outils.exiger_probleme(reponse, 503, "SERVICE_INDISPONIBLE", "A commande, Paiements en panne")
    commandes = await plateforme.bases.commandes_de("client-a")
    assert [c["statut"] for c in commandes] == ["EN_ATTENTE"], commandes
    plateforme.retablir()
    return str(commandes[0]["id"])


async def test_une_place_perdue_avant_paiement_expire_la_commande_sans_debit(
    plateforme_courte: Any, outils: Any
) -> None:
    plateforme = plateforme_courte
    commande_a = await _commande_en_attente_apres_panne(plateforme, outils)
    await anyio.sleep(ATTENTE_EXPIRATION)

    reponse_b = await plateforme.commander("B", ["A1"])
    reponse_a = await plateforme.payer("A", commande_a)

    outils.exiger_statut(reponse_b, 201, "B commande A1 après expiration")
    outils.exiger_probleme(reponse_a, 409, "SEAT_ALREADY_TAKEN", "A paie après expiration")
    assert (await plateforme.bases.commande(commande_a))["statut"] == "EXPIREE"
    assert await plateforme.bases.paiements_de(commande_a) == []


async def test_payer_apres_expire_le_renvoie_409_et_expire_la_commande(
    plateforme_courte: Any, outils: Any
) -> None:
    plateforme = plateforme_courte
    commande_a = await _commande_en_attente_apres_panne(plateforme, outils)
    await anyio.sleep(ATTENTE_EXPIRATION)

    reponse = await plateforme.payer("A", commande_a)

    outils.exiger_probleme(reponse, 409, "SEAT_ALREADY_TAKEN", "payerCommande après expire_le")
    assert (await plateforme.bases.commande(commande_a))["statut"] == "EXPIREE"
    expirees = await plateforme.bases.evenements_de("ticketing.order.expired", commande_a)
    assert len(expirees) == 1, expirees
    assert outils.erreurs_evenement(expirees[0]) == []
    assert await plateforme.bases.paiements_de(commande_a) == []
