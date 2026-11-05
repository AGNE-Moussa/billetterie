"""Débit sans commande confirmée (review BIL-008, point 3) et séance lue dans Catalogue par
`payerCommande` (décisions d'implémentation).

Avant d'expirer une commande déjà envoyée à Paiements, Commandes rejoue la clé : si le paiement
est ACCEPTE, `ticketing.order.expired` porte `remboursement_du: true` (schéma
docs/evenements/ticketing.order.expired.json) ; sans paiement accepté, le champ est absent ou
faux, et aucun débit n'est créé. `payerCommande` sur une séance annulée ou commencée d'après
Catalogue : 409, commande EXPIREE, `order.expired` ; séance inconnue : 404 SHOW_NOT_FOUND.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

pytestmark = pytest.mark.anyio

EXPIREE = "ticketing.order.expired"
CONFIRMEE = "ticketing.order.confirmed"


async def _place_perdue(plateforme: Any) -> None:
    plateforme.perdre_place_au_reverrouillage("A1")


async def _seance_annulee(plateforme: Any) -> None:
    plateforme.catalogue.ajouter(
        plateforme.seance, datetime.now(UTC) + timedelta(days=30), annulee=True
    )


async def _seance_commencee(plateforme: Any) -> None:
    plateforme.catalogue.ajouter(plateforme.seance, datetime.now(UTC) - timedelta(hours=1))


# (cause, code attendu de payerCommande)
CAUSES: dict[str, tuple[Callable[[Any], Awaitable[None]], str]] = {
    "place-perdue": (_place_perdue, "SEAT_ALREADY_TAKEN"),
    "seance-annulee": (_seance_annulee, "SHOW_CANCELLED"),
    "seance-commencee": (_seance_commencee, "SHOW_ALREADY_STARTED"),
}


async def _commande_debitee_sans_reponse(plateforme: Any, outils: Any) -> str:
    """Les trois réponses de Paiements perdues après enregistrement : 503, commande EN_ATTENTE,
    paiement ACCEPTE ; Paiements rétabli."""
    plateforme.perdre_reponses_paiements()
    reponse = await plateforme.commander("A", ["A1"])
    outils.exiger_probleme(reponse, 503, "SERVICE_INDISPONIBLE", "réponses de Paiements perdues")
    (commande,) = await plateforme.bases.commandes_de("client-a")
    assert commande["statut"] == "EN_ATTENTE", commande
    assert [p["statut"] for p in await plateforme.bases.paiements_de(commande["id"])] == ["ACCEPTE"]
    plateforme.retablir()
    return str(commande["id"])


async def _commande_sans_paiement(plateforme: Any, outils: Any) -> str:
    """Paiements injoignable : 503, commande EN_ATTENTE, aucun paiement ; Paiements rétabli."""
    plateforme.paiements_injoignable()
    reponse = await plateforme.commander("A", ["A1"])
    outils.exiger_probleme(reponse, 503, "SERVICE_INDISPONIBLE", "Paiements injoignable")
    (commande,) = await plateforme.bases.commandes_de("client-a")
    assert commande["statut"] == "EN_ATTENTE", commande
    assert await plateforme.bases.paiements_de(commande["id"]) == []
    plateforme.retablir()
    return str(commande["id"])


@pytest.mark.parametrize("cause", list(CAUSES))
async def test_une_commande_debitee_puis_expiree_signale_le_remboursement_du(
    plateforme: Any, outils: Any, cause: str
) -> None:
    provoquer, code = CAUSES[cause]
    commande_id = await _commande_debitee_sans_reponse(plateforme, outils)
    (paiement_avant,) = await plateforme.bases.paiements_de(commande_id)
    await provoquer(plateforme)

    reponse = await plateforme.payer("A", commande_id)

    outils.exiger_probleme(reponse, 409, code, f"payerCommande, {cause}")
    assert (await plateforme.bases.commande(commande_id))["statut"] == "EXPIREE"
    expirees = await plateforme.bases.evenements_de(EXPIREE, commande_id)
    assert len(expirees) == 1, expirees
    assert outils.erreurs_evenement(expirees[0]) == []
    assert expirees[0]["data"].get("remboursement_du") is True, expirees[0]["data"]
    assert await plateforme.bases.evenements_de(CONFIRMEE, commande_id) == []
    paiements = await plateforme.bases.paiements_de(commande_id)
    assert [p["id"] for p in paiements] == [paiement_avant["id"]], "second débit"


@pytest.mark.parametrize("cause", list(CAUSES))
async def test_une_commande_expiree_sans_paiement_accepte_ne_signale_aucun_remboursement(
    plateforme: Any, outils: Any, cause: str
) -> None:
    provoquer, code = CAUSES[cause]
    commande_id = await _commande_sans_paiement(plateforme, outils)
    await provoquer(plateforme)

    reponse = await plateforme.payer("A", commande_id)

    outils.exiger_probleme(reponse, 409, code, f"payerCommande, {cause}")
    assert (await plateforme.bases.commande(commande_id))["statut"] == "EXPIREE"
    expirees = await plateforme.bases.evenements_de(EXPIREE, commande_id)
    assert len(expirees) == 1, expirees
    assert outils.erreurs_evenement(expirees[0]) == []
    assert expirees[0]["data"].get("remboursement_du") in (None, False), expirees[0]["data"]
    # Le rejeu de la clé ne doit pas créer de débit.
    assert await plateforme.bases.paiements_de(commande_id) == []


async def test_payer_une_commande_d_une_seance_inconnue_renvoie_404_show_not_found(
    plateforme: Any, outils: Any
) -> None:
    commande_id = await _commande_sans_paiement(plateforme, outils)
    del plateforme.catalogue.seances[str(plateforme.seance.id)]

    reponse = await plateforme.payer("A", commande_id)

    outils.exiger_probleme(reponse, 404, "SHOW_NOT_FOUND", "payerCommande, séance inconnue")
    assert await plateforme.bases.paiements_de(commande_id) == []
    assert await plateforme.bases.evenements_de(CONFIRMEE, commande_id) == []
