"""CA1 (BIL-008, décision Q2) en concurrence : la même place disputée par plusieurs clients sur
les deux instances de Commandes (même base), avec le vrai Billets (vrai Redis) et le vrai
Paiements. Les appels partent ensemble après une barrière.

Marqueur `concurrence` : garantie centrale du projet (une place n'est jamais vendue deux fois),
joué par `make test-concurrence` comme BIL-007.
"""

from collections import Counter
from typing import Any

import pytest

pytestmark = [pytest.mark.anyio, pytest.mark.concurrence]

CLIENTS_SIMULTANES = 20
TOURS = 20


def _client(numero: int) -> dict[str, Any]:
    return {
        "sujet": f"client-concurrence-{numero:02d}",
        "roles": ["customer"],
        "scopes": ["orders:read", "orders:write"],
    }


async def _commandes_contenant(plateforme: Any, place_id: Any) -> list[dict[str, Any]]:
    return await plateforme.bases.commandes.lignes(
        "SELECT c.id, c.statut FROM commandes c JOIN lignes_commande l ON l.commande_id = c.id"
        " WHERE l.place_id = :place",
        place=place_id,
    )


async def test_deux_clients_commandant_la_meme_place_en_parallele_n_ont_qu_un_gagnant(
    plateforme: Any, outils: Any
) -> None:
    async def appel(numero: int) -> Any:
        qui = ("A", "B")[numero]
        return await plateforme.commander(qui, ["A1"], instance=plateforme.instance(numero))

    reponses = await outils.barriere(2, appel)

    statuts = sorted(reponse.status_code for reponse in reponses)
    assert statuts == [201, 409], [reponse.text for reponse in reponses]
    gagnante = next(r for r in reponses if r.status_code == 201).json()
    perdante = next(r for r in reponses if r.status_code == 409)
    assert gagnante["statut"] == "CONFIRMEE"
    assert perdante.json()["code"] == "SEAT_ALREADY_TAKEN"
    paiements = await plateforme.bases.paiements_de()
    assert [p["statut"] for p in paiements] == ["ACCEPTE"]
    assert str(paiements[0]["commande_id"]) == gagnante["id"]
    assert await plateforme.redis.valeur(plateforme.cle_redis("A1")) == gagnante["id"]
    autres = [
        c
        for c in await _commandes_contenant(plateforme, plateforme.seance.places["A1"])
        if str(c["id"]) != gagnante["id"]
    ]
    assert [c["statut"] for c in autres] == ["EXPIREE"]


async def test_vingt_clients_sur_la_meme_place_ne_paient_qu_une_fois(
    plateforme: Any, outils: Any
) -> None:
    async def appel(numero: int) -> Any:
        return await plateforme.commander(
            _client(numero), ["A1"], instance=plateforme.instance(numero)
        )

    reponses = await outils.barriere(CLIENTS_SIMULTANES, appel)

    statuts = Counter(reponse.status_code for reponse in reponses)
    assert not [s for s in statuts if s >= 500], statuts
    assert statuts == {201: 1, 409: CLIENTS_SIMULTANES - 1}, statuts
    assert all(r.json()["code"] == "SEAT_ALREADY_TAKEN" for r in reponses if r.status_code == 409)
    assert len(await plateforme.bases.paiements_de()) == 1
    contenant = await _commandes_contenant(plateforme, plateforme.seance.places["A1"])
    assert [c["statut"] for c in contenant].count("CONFIRMEE") == 1, contenant


async def test_deux_commandes_qui_se_chevauchent_ne_vendent_jamais_la_place_commune_deux_fois(
    plateforme: Any, outils: Any
) -> None:
    demandes = (("A", "client-a", ["A1", "A2"]), ("B", "client-b", ["A2", "A3"]))
    for tour in range(TOURS):
        # Nouvelle séance à chaque tour : ni place ni plafond hérités du tour précédent.
        seance = await plateforme.nouvelle_seance()

        async def appel(numero: int, seance: Any = seance) -> Any:
            qui, _sujet, libelles = demandes[numero]
            return await plateforme.commander(
                qui, libelles, seance=seance, instance=plateforme.instance(numero)
            )

        reponses = await outils.barriere(2, appel)

        assert all(r.status_code in (201, 409) for r in reponses), (
            tour,
            [r.text for r in reponses],
        )
        contenant = await _commandes_contenant(plateforme, seance.places["A2"])
        statuts = [c["statut"] for c in contenant]
        assert statuts.count("CONFIRMEE") <= 1, (tour, contenant)
        assert len(contenant) == 2, (tour, contenant)
        for (_qui, sujet, _libelles), reponse in zip(demandes, reponses, strict=True):
            if reponse.status_code != 201:
                perdante = await plateforme.bases.commandes.lignes(
                    "SELECT statut FROM commandes WHERE seance_id = :s AND client = :c",
                    s=seance.id,
                    c=sujet,
                )
                assert [c["statut"] for c in perdante] == ["EXPIREE"], (tour, perdante)
