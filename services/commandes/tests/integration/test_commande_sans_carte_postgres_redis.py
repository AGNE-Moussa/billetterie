"""BIL-020 (décision Q1 de BIL-018) : creerCommande sans carte_test, en vraie base et vrai Redis.

Sans carte : 201 EN_ATTENTE, places verrouillées dans Redis (durée de réservation) jusqu'à
`expire_le`, aucun appel à Paiements ; le client paie ensuite par payerCommande, qui reverrouille
en durée de confirmation et confirme la commande. Concurrence : deux commandes sans carte sur la
même place, une seule obtient 201, l'autre 409 SEAT_ALREADY_TAKEN.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from commandes.infra.clients import CIBLE_PAIEMENTS

pytestmark = pytest.mark.anyio

DUREE_RESERVATION_MS = 600_000
TOLERANCE = timedelta(seconds=3)


async def _commander_sans_carte(
    plateforme: Any,
    outils: Any,
    qui: str,
    libelles: list[str],
    *,
    carte_nulle: bool = False,
    instance: Any = None,
) -> Any:
    corps: dict[str, Any] = {
        "seance_id": str(plateforme.seance.id),
        "place_ids": plateforme.seance.ids(*libelles),
    }
    if carte_nulle:
        corps["carte_test"] = None
    client = instance or plateforme.commandes_1
    return await outils.borne(
        "POST /api/v1/orders sans carte",
        client.post(outils.route_commandes, json=corps, headers=plateforme.entetes(qui)),
    )


@pytest.mark.parametrize("carte_nulle", [False, True], ids=["carte_absente", "carte_null"])
async def test_une_commande_sans_carte_reste_en_attente_avec_ses_places_verrouillees(
    plateforme: Any, outils: Any, carte_nulle: bool
) -> None:
    avant = datetime.now(UTC)
    corps = outils.exiger_statut(
        await _commander_sans_carte(plateforme, outils, "A", ["A1", "C1"], carte_nulle=carte_nulle),
        201,
        "creerCommande sans carte",
    )

    assert outils.erreurs_schema(corps, "commandes", "Commande") == []
    assert corps["statut"] == "EN_ATTENTE"
    assert corps["montant_total"] == plateforme.seance.prix["A1"] + plateforme.seance.prix["C1"]
    expire_le = outils.lire_instant(corps["expire_le"])
    attendu = avant + timedelta(milliseconds=DUREE_RESERVATION_MS)
    assert abs(expire_le - attendu) <= TOLERANCE, corps["expire_le"]

    ligne = await plateforme.bases.commande(corps["id"])
    assert ligne["statut"] == "EN_ATTENTE"
    assert ligne["paiement_demande"] is False
    assert abs(ligne["expire_le"] - expire_le) < timedelta(seconds=1)
    for libelle in ("A1", "C1"):
        cle = plateforme.cle_redis(libelle)
        assert await plateforme.redis.valeur(cle) == corps["id"], libelle
        echeance_verrou = datetime.now(UTC) + timedelta(
            milliseconds=await plateforme.redis.pttl(cle)
        )
        assert abs(echeance_verrou - expire_le) <= TOLERANCE, libelle

    assert plateforme.gateway.appels_vers(CIBLE_PAIEMENTS) == []
    assert await plateforme.bases.paiements_de() == []
    assert await plateforme.bases.outbox("ticketing.order.confirmed") == []


async def test_une_commande_sans_carte_se_paie_ensuite_par_payer_commande(
    plateforme: Any, outils: Any
) -> None:
    creee = outils.exiger_statut(
        await _commander_sans_carte(plateforme, outils, "A", ["A2"]),
        201,
        "creerCommande sans carte",
    )

    payee = outils.exiger_statut(await plateforme.payer("A", creee["id"]), 200, "payerCommande")

    assert payee["statut"] == "CONFIRMEE"
    assert payee["id"] == creee["id"]
    assert await plateforme.bases.statut(creee["id"]) == "CONFIRMEE"
    paiements = await plateforme.bases.paiements_de(creee["id"])
    assert [p["statut"] for p in paiements] == ["ACCEPTE"]
    assert paiements[0]["montant"] == plateforme.seance.prix["A2"]
    cle = plateforme.cle_redis("A2")
    assert await plateforme.redis.valeur(cle) == creee["id"]
    # Reverrouillage en durée de confirmation (1 h) juste avant Paiements.
    assert await plateforme.redis.pttl(cle) > DUREE_RESERVATION_MS
    assert len(await plateforme.bases.evenements_de("ticketing.order.confirmed", creee["id"])) == 1


@pytest.mark.concurrence
async def test_deux_commandes_sans_carte_sur_la_meme_place_n_ont_qu_un_gagnant(
    plateforme: Any, outils: Any
) -> None:
    async def appel(numero: int) -> Any:
        return await _commander_sans_carte(
            plateforme, outils, ("A", "B")[numero], ["A3"], instance=plateforme.instance(numero)
        )

    reponses = await outils.barriere(2, appel)

    statuts = sorted(r.status_code for r in reponses)
    assert statuts == [201, 409], [r.text for r in reponses]
    gagnante = next(r for r in reponses if r.status_code == 201).json()
    perdante = next(r for r in reponses if r.status_code == 409)
    outils.exiger_probleme(perdante, 409, "SEAT_ALREADY_TAKEN", "commande perdante")
    assert gagnante["statut"] == "EN_ATTENTE"
    assert await plateforme.redis.valeur(plateforme.cle_redis("A3")) == gagnante["id"]
    contenant = await plateforme.bases.commandes.lignes(
        "SELECT c.id, c.statut FROM commandes c JOIN lignes_commande l ON l.commande_id = c.id"
        " WHERE l.place_id = :place",
        place=plateforme.seance.places["A3"],
    )
    statuts_base = sorted(str(c["statut"]) for c in contenant)
    assert statuts_base == ["EN_ATTENTE", "EXPIREE"], contenant
    assert await plateforme.bases.paiements_de() == []
