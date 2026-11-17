"""E7 (BIL-008, décision Q10, contrat) : base de Commandes en pause (`docker pause`) et Paiements
injoignable (`ConnectError` simulé par la gateway de test).

`creerCommande` est appelée avec une `Idempotency-Key` : d'après l'ordre des contrôles (Q14),
la clé se réserve en base avant toute lecture de la séance, donc avant tout appel sortant.
"""

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import pytest
from testcontainers.community.postgres import PostgresContainer

pytestmark = pytest.mark.anyio

DELAI_BASE = 1.0
# Borne d'une réponse pendant la pause de la base : delai_base + 5 s (comme billets).
REPONSE_BASE_MAXIMALE = DELAI_BASE + 5.0
TOLERANCE_TTL_MS = 5_000


@pytest.fixture
async def plateforme_delai_court(
    plateforme_commandes: Callable[..., AbstractAsyncContextManager[Any]],
) -> AsyncIterator[Any]:
    async with plateforme_commandes(commandes={"delai_base": DELAI_BASE}) as demarree:
        yield demarree


@pytest.mark.parametrize(
    "operation", ["creerCommande", "listerCommandes", "lireCommande", "payerCommande"]
)
async def test_base_injoignable_les_routes_de_commandes_renvoient_503(
    operation: str, plateforme_delai_court: Any, postgres: PostgresContainer, outils: Any
) -> None:
    plateforme = plateforme_delai_court
    route = outils.route_commandes
    entetes = plateforme.entetes("A")
    inconnue = uuid.uuid4()
    client = plateforme.commandes_1
    if operation == "creerCommande":
        appel = client.post(
            route,
            json={
                "seance_id": str(plateforme.seance.id),
                "place_ids": plateforme.seance.ids("A1"),
                "carte_test": outils.carte_acceptee,
            },
            headers={**entetes, "Idempotency-Key": "cle-bil-008-base"},
        )
    elif operation == "listerCommandes":
        appel = client.get(route, headers=entetes)
    elif operation == "lireCommande":
        appel = client.get(f"{route}/{inconnue}", headers=entetes)
    else:
        appel = client.post(
            f"{route}/{inconnue}/payment",
            json={"carte_test": outils.carte_acceptee},
            headers=entetes,
        )
    conteneur = postgres.get_wrapped_container()
    conteneur.pause()
    try:
        reponse = await outils.borne(f"{operation}, base en pause", appel, REPONSE_BASE_MAXIMALE)
    finally:
        conteneur.unpause()

    outils.exiger_probleme(reponse, 503, "BASE_INDISPONIBLE", f"{operation}, base en pause")
    assert "postgresql" not in reponse.text.lower()
    assert plateforme.gateway.appels == []


async def test_paiements_indisponible_laisse_la_commande_en_attente_et_retrouvable(
    plateforme: Any, outils: Any
) -> None:
    plateforme.paiements_injoignable()

    reponse = await plateforme.commander("A", ["A1", "C1"])

    outils.exiger_probleme(reponse, 503, "SERVICE_INDISPONIBLE", "Paiements injoignable")
    commandes = await plateforme.bases.commandes_de("client-a")
    assert [c["statut"] for c in commandes] == ["EN_ATTENTE"]
    commande_id = str(commandes[0]["id"])
    for libelle in ("A1", "C1"):
        cle = plateforme.cle_redis(libelle)
        assert await plateforme.redis.valeur(cle) == commande_id, libelle
        ttl = await plateforme.redis.pttl(cle)
        assert abs(ttl - outils.duree_confirmation_ms) <= TOLERANCE_TTL_MS, (libelle, ttl)
    page = outils.exiger_statut(await plateforme.lister("A"), 200, "listerCommandes")
    assert [(e["id"], e["statut"]) for e in page["elements"]] == [(commande_id, "EN_ATTENTE")]
