"""CA1 (BIL-008, décisions Q1 et Q2) : une commande ne porte que des places verrouillées à son
profit, sur le vrai Billets (sa base, vrai Redis) et le vrai Paiements.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

pytestmark = pytest.mark.anyio

TOLERANCE_TTL_MS = 5_000
TOLERANCE_EXPIRATION = timedelta(seconds=5)


async def test_une_place_deja_verrouillee_pour_un_autre_client_est_refusee(
    plateforme: Any, outils: Any
) -> None:
    autre_commande = await plateforme.verrouiller_pour_autrui("C1")
    cle_c1 = plateforme.cle_redis("C1")
    ttl_avant = await plateforme.redis.pttl(cle_c1)

    reponse = await plateforme.commander("A", ["A1", "C1"])

    outils.exiger_probleme(reponse, 409, "SEAT_ALREADY_TAKEN", "A commande A1 et C1")
    (commande,) = await plateforme.bases.commandes_de("client-a")
    assert commande["statut"] == "EXPIREE"
    assert await plateforme.redis.valeur(cle_c1) == str(autre_commande)
    assert await plateforme.redis.pttl(cle_c1) <= ttl_avant
    assert await plateforme.bases.paiements_de() == []


async def test_une_place_vendue_est_refusee(plateforme: Any, outils: Any) -> None:
    await plateforme.bases.vendre(plateforme.seance.id, plateforme.seance.places["A1"])

    reponse = await plateforme.commander("A", ["A1"])

    outils.exiger_probleme(reponse, 409, "SEAT_ALREADY_TAKEN", "A commande A1 vendue")
    (commande,) = await plateforme.bases.commandes_de("client-a")
    assert commande["statut"] == "EXPIREE"
    assert await plateforme.bases.paiements_de() == []


async def test_une_commande_confirmee_laisse_les_verrous_redis_a_son_nom_pour_une_heure(
    plateforme: Any, outils: Any
) -> None:
    reponse = await plateforme.commander("A", ["A1", "A2"])

    corps = outils.exiger_statut(reponse, 201, "A commande A1 et A2")
    for libelle in ("A1", "A2"):
        cle = plateforme.cle_redis(libelle)
        assert await plateforme.redis.valeur(cle) == corps["id"], libelle
        ttl = await plateforme.redis.pttl(cle)
        assert abs(ttl - outils.duree_confirmation_ms) <= TOLERANCE_TTL_MS, (libelle, ttl)
    attendu = datetime.now(UTC) + timedelta(seconds=3600)
    assert abs(outils.lire_instant(corps["expire_le"]) - attendu) <= TOLERANCE_EXPIRATION
