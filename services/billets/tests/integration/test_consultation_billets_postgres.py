"""BIL-021 : listerBillets et lireBillet en vraie base (PostgreSQL migré par Alembic).

Billets synthétiques écrits directement dans la table `billets` (propriétaire : `billets.client`,
le `sub` du jeton), sur des places semées de la séance commune. Les lectures passent par l'API
(`plateforme.public`, sans jeton de service), avec des jetons `EmetteurDeTest`.

Vérifié : isolation entre deux clients et un revendeur (liste et lecture), filtre `commande_id`
toujours combiné à l'appelant, `rang`/`numero` lus par jointure sur la place, tri par émission
décroissante, et lectures simultanées de plusieurs appelants (cas de concurrence de la rule).
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

pytestmark = pytest.mark.anyio

ROUTE_BILLETS = "/api/v1/tickets"
SCOPES = ["tickets:read"]
CLIENT_A = {"sujet": "client-a-billets", "roles": ["customer"], "scopes": SCOPES}
CLIENT_B = {"sujet": "client-b-billets", "roles": ["customer"], "scopes": SCOPES}
REVENDEUR = {
    "sujet": "service-account-revendeur-test",
    "roles": ["partner"],
    "scopes": SCOPES,
    "client": "revendeur-test",
}


async def _emettre(
    base: Any,
    seance: Any,
    libelle: str,
    *,
    client: str,
    commande_id: uuid.UUID,
    emis_le: datetime,
) -> str:
    billet_id = uuid.uuid4()
    await base.executer(
        "INSERT INTO billets (id, commande_id, client, seance_id, place_id, statut, qr_code,"
        " emis_le) VALUES (:id, :commande_id, :client, :seance_id, :place_id, 'EMIS',"
        " :qr_code, :emis_le)",
        id=billet_id,
        commande_id=commande_id,
        client=client,
        seance_id=seance.id,
        place_id=seance.places[libelle],
        qr_code=f"qr-de-test-{billet_id}",
        emis_le=emis_le,
    )
    return str(billet_id)


async def _semer(base: Any, seance: Any) -> dict[str, Any]:
    """A : commande 1 (A1, A2) puis commande 2 (B3) ; B : C1 ; revendeur : C2."""
    t0 = datetime.now(UTC) - timedelta(hours=1)
    commande_a1, commande_a2, commande_b, commande_r = (uuid.uuid4() for _ in range(4))
    a = CLIENT_A["sujet"]
    ids = {
        "A1": await _emettre(base, seance, "A1", client=a, commande_id=commande_a1, emis_le=t0),
        "A2": await _emettre(
            base, seance, "A2", client=a, commande_id=commande_a1, emis_le=t0 + timedelta(seconds=1)
        ),
        "B3": await _emettre(
            base, seance, "B3", client=a, commande_id=commande_a2, emis_le=t0 + timedelta(minutes=5)
        ),
        "C1": await _emettre(
            base,
            seance,
            "C1",
            client=CLIENT_B["sujet"],
            commande_id=commande_b,
            emis_le=t0 + timedelta(minutes=10),
        ),
        "C2": await _emettre(
            base,
            seance,
            "C2",
            client=REVENDEUR["sujet"],
            commande_id=commande_r,
            emis_le=t0 + timedelta(minutes=10),
        ),
    }
    return {
        "billets": ids,
        "commande_a1": commande_a1,
        "commande_a2": commande_a2,
        "commande_b": commande_b,
    }


async def _lister(plateforme: Any, emetteur: Any, qui: dict[str, Any], **parametres: Any) -> Any:
    return await plateforme.public.get(
        ROUTE_BILLETS, params=parametres, headers=emetteur.entetes(**qui)
    )


async def _lire(plateforme: Any, emetteur: Any, qui: dict[str, Any], billet_id: str) -> Any:
    return await plateforme.public.get(
        f"{ROUTE_BILLETS}/{billet_id}", headers=emetteur.entetes(**qui)
    )


async def test_chaque_appelant_ne_liste_que_ses_propres_billets(
    plateforme: Any, base: Any, seance: Any, emetteur: Any, outils: Any, composants: Any
) -> None:
    semes = await _semer(base, seance)
    billets = semes["billets"]

    attendus = {
        "A": (CLIENT_A, [billets["B3"], billets["A2"], billets["A1"]]),
        "B": (CLIENT_B, [billets["C1"]]),
        "revendeur": (REVENDEUR, [billets["C2"]]),
    }
    for nom, (qui, ids) in attendus.items():
        corps = outils.exiger_statut(
            await _lister(plateforme, emetteur, qui), 200, f"listerBillets ({nom})"
        )
        assert outils.erreurs_schema(corps, "BilletPage", composants) == [], nom
        assert [e["id"] for e in corps["elements"]] == ids, f"{nom} : {corps}"
        assert corps["total"] == len(ids), nom


async def test_un_billet_d_un_autre_appelant_repond_404_comme_un_billet_inexistant(
    plateforme: Any, base: Any, seance: Any, emetteur: Any, outils: Any
) -> None:
    billets = (await _semer(base, seance))["billets"]

    for qui, billet in (
        (CLIENT_B, billets["A1"]),
        (REVENDEUR, billets["A1"]),
        (CLIENT_A, billets["C2"]),
        (CLIENT_A, str(uuid.uuid4())),
    ):
        outils.exiger_probleme(
            await _lire(plateforme, emetteur, qui, billet),
            404,
            "TICKET_NOT_FOUND",
            f"lireBillet {billet} par {qui['sujet']}",
        )
    outils.exiger_statut(
        await _lire(plateforme, emetteur, REVENDEUR, billets["C2"]),
        200,
        "lireBillet du revendeur",
    )


async def test_le_filtre_commande_id_reste_combine_a_l_appelant(
    plateforme: Any, base: Any, seance: Any, emetteur: Any, outils: Any
) -> None:
    semes = await _semer(base, seance)
    billets = semes["billets"]

    propre = outils.exiger_statut(
        await _lister(plateforme, emetteur, CLIENT_A, commande_id=str(semes["commande_a1"])),
        200,
        "listerBillets de A, commande 1",
    )
    assert [e["id"] for e in propre["elements"]] == [billets["A2"], billets["A1"]]
    assert propre["total"] == 2
    assert {e["commande_id"] for e in propre["elements"]} == {str(semes["commande_a1"])}

    for qui, commande, etape in (
        (CLIENT_B, semes["commande_a1"], "commande de A demandée par B"),
        (REVENDEUR, semes["commande_a1"], "commande de A demandée par le revendeur"),
        (CLIENT_A, semes["commande_b"], "commande de B demandée par A"),
        (CLIENT_A, uuid.uuid4(), "commande inconnue"),
    ):
        corps = outils.exiger_statut(
            await _lister(plateforme, emetteur, qui, commande_id=str(commande)), 200, etape
        )
        assert corps["elements"] == [], f"{etape} : {corps}"
        assert corps["total"] == 0, etape


async def test_rang_et_numero_viennent_de_la_place_du_billet(
    plateforme: Any, base: Any, seance: Any, emetteur: Any, outils: Any, composants: Any
) -> None:
    billets = (await _semer(base, seance))["billets"]

    for libelle in ("A1", "A2", "B3"):
        corps = outils.exiger_statut(
            await _lire(plateforme, emetteur, CLIENT_A, billets[libelle]),
            200,
            f"lireBillet {libelle}",
        )
        assert outils.erreurs_schema(corps, "Billet", composants) == [], libelle
        assert (corps["rang"], corps["numero"]) == (libelle[0], int(libelle[1:])), corps
        assert corps["place_id"] == str(seance.places[libelle])
        assert corps["seance_id"] == str(seance.id)
        assert corps["qr_code"] == f"qr-de-test-{billets[libelle]}"

    liste = outils.exiger_statut(
        await _lister(plateforme, emetteur, CLIENT_A), 200, "listerBillets de A"
    )
    assert [(e["rang"], e["numero"]) for e in liste["elements"]] == [("B", 3), ("A", 2), ("A", 1)]


async def test_des_lectures_simultanees_de_plusieurs_appelants_restent_isolees(
    plateforme: Any, base: Any, seance: Any, emetteur: Any, outils: Any
) -> None:
    billets = (await _semer(base, seance))["billets"]
    appelants = [CLIENT_A, CLIENT_B, REVENDEUR] * 5

    reponses = await outils.borne(
        "lectures simultanées",
        asyncio.gather(*(_lister(plateforme, emetteur, qui) for qui in appelants)),
    )

    attendus = {
        CLIENT_A["sujet"]: {billets["A1"], billets["A2"], billets["B3"]},
        CLIENT_B["sujet"]: {billets["C1"]},
        REVENDEUR["sujet"]: {billets["C2"]},
    }
    for qui, reponse in zip(appelants, reponses, strict=True):
        corps = outils.exiger_statut(reponse, 200, f"listerBillets ({qui['sujet']})")
        assert {e["id"] for e in corps["elements"]} == attendus[qui["sujet"]], qui["sujet"]
