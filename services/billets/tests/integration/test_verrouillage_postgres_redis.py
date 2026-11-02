"""CA1 et E2 (BIL-006) : verrouillage d'une place sur vraie base et vrai Redis.

Deux instances de l'application (`instance_1`, `instance_2`) partagent la base et le Redis du
module, comme `billets-1` et `billets-2`. Les appels simultanés partent par `asyncio.gather`
(décision Q24 : 50 PUT, 50 commandes différentes, répartis sur les deux instances).
"""

import asyncio
import logging
import uuid
from collections import Counter
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.anyio

VERROUILLAGES_SIMULTANES = 50
PLACES_DIFFERENTES = 20


async def test_le_verrou_pose_dans_redis_a_pour_valeur_la_commande_et_une_expiration(
    plateforme: Any, seance: Any, observateur: Any, outils: Any
) -> None:
    commande_a = uuid.uuid4()
    place = seance.places["A1"]

    reponse = await plateforme.verrouiller(seance.id, place, commande_a)

    outils.exiger_statut(reponse, 200, "verrou de commande_a")
    cle = outils.cle_verrou(seance.id, place)
    assert await observateur.valeur(cle) == str(commande_a)
    assert 595_000 <= await observateur.pttl(cle) <= 600_000


async def test_une_autre_commande_recoit_409_sur_une_place_verrouillee_dans_redis(
    plateforme: Any, seance: Any, observateur: Any, outils: Any
) -> None:
    commande_a, commande_b = uuid.uuid4(), uuid.uuid4()
    place = seance.places["A1"]
    cle = outils.cle_verrou(seance.id, place)

    premier = await plateforme.verrouiller(
        seance.id, place, commande_a, client=plateforme.instance_1
    )
    outils.exiger_statut(premier, 200, "verrou de commande_a par l'instance 1")
    pttl_avant = await observateur.pttl(cle)

    second = await plateforme.verrouiller(
        seance.id, place, commande_b, client=plateforme.instance_2
    )

    outils.exiger_probleme(second, 409, "SEAT_ALREADY_TAKEN", "commande_b par l'instance 2")
    assert await observateur.valeur(cle) == str(commande_a)
    assert abs(await observateur.pttl(cle) - pttl_avant) <= 1_000


async def _verrouillages_simultanes(
    plateforme: Any, seance_id: uuid.UUID, place: uuid.UUID, commandes: list[uuid.UUID]
) -> list[httpx.Response]:
    return list(
        await asyncio.gather(
            *(
                plateforme.verrouiller(
                    seance_id, place, commande, client=plateforme.instance(numero)
                )
                for numero, commande in enumerate(commandes)
            )
        )
    )


async def test_cinquante_verrouillages_simultanes_de_la_meme_place_n_ont_qu_un_gagnant(
    plateforme: Any, seance: Any, observateur: Any, outils: Any
) -> None:
    place = seance.places["A1"]
    commandes = [uuid.uuid4() for _ in range(VERROUILLAGES_SIMULTANES)]

    reponses = await outils.borne(
        f"{VERROUILLAGES_SIMULTANES} PUT simultanés",
        _verrouillages_simultanes(plateforme, seance.id, place, commandes),
    )

    statuts = Counter(reponse.status_code for reponse in reponses)
    assert statuts == {200: 1, 409: VERROUILLAGES_SIMULTANES - 1}, statuts
    refus = [r for r in reponses if r.status_code == 409]
    assert {r.json()["code"] for r in refus} == {"SEAT_ALREADY_TAKEN"}
    (gagnant,) = [
        commande for commande, r in zip(commandes, reponses, strict=True) if r.status_code == 200
    ]
    assert await observateur.valeur(outils.cle_verrou(seance.id, place)) == str(gagnant)


async def test_des_verrouillages_simultanes_de_places_differentes_reussissent_tous(
    plateforme: Any, seance: Any, observateur: Any, outils: Any
) -> None:
    libelles = seance.ordre()[:PLACES_DIFFERENTES]
    commandes = {libelle: uuid.uuid4() for libelle in libelles}

    reponses = await outils.borne(
        f"{PLACES_DIFFERENTES} PUT simultanés sur des places différentes",
        asyncio.gather(
            *(
                plateforme.verrouiller(
                    seance.id,
                    seance.places[libelle],
                    commandes[libelle],
                    client=plateforme.instance(numero),
                )
                for numero, libelle in enumerate(libelles)
            )
        ),
    )

    statuts = Counter(reponse.status_code for reponse in reponses)
    assert statuts == {200: PLACES_DIFFERENTES}, statuts
    cles = {
        outils.cle_verrou(seance.id, seance.places[libelle]): str(commandes[libelle])
        for libelle in libelles
    }
    assert sorted(await observateur.cles()) == sorted(cles)
    for cle, commande in cles.items():
        assert await observateur.valeur(cle) == commande, cle


async def test_un_billet_insere_bloque_le_verrouillage_d_une_place_sans_verrou(
    plateforme: Any, seance: Any, base: Any, observateur: Any, outils: Any
) -> None:
    place = seance.places["A2"]
    await base.inserer_billet(seance.id, place, statut="EMIS")

    reponse = await plateforme.verrouiller(seance.id, place, uuid.uuid4())

    outils.exiger_probleme(reponse, 409, "SEAT_ALREADY_TAKEN", "verrou d'une place vendue")
    assert await observateur.cles() == []


async def test_une_place_inconnue_renvoie_404_meme_si_une_cle_redis_existe(
    plateforme: Any, seance: Any, observateur: Any, outils: Any
) -> None:
    inconnue = uuid.uuid4()
    await observateur.poser(outils.cle_verrou(seance.id, inconnue), str(uuid.uuid4()), 60_000)

    reponse = await plateforme.verrouiller(seance.id, inconnue, uuid.uuid4())

    outils.exiger_probleme(reponse, 404, "SEAT_NOT_FOUND", "verrou d'une place inconnue")


async def test_un_conflit_n_est_jamais_une_erreur_500(
    plateforme: Any,
    seance: Any,
    outils: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    place = seance.places["B1"]
    commandes = [uuid.uuid4() for _ in range(VERROUILLAGES_SIMULTANES)]

    reponses = await outils.borne(
        f"{VERROUILLAGES_SIMULTANES} PUT simultanés",
        _verrouillages_simultanes(plateforme, seance.id, place, commandes),
    )

    erreurs_serveur = [(r.status_code, r.text[:200]) for r in reponses if r.status_code >= 500]
    assert erreurs_serveur == [], erreurs_serveur
    assert all("Traceback" not in r.text for r in reponses)
    jeton = plateforme.instance_1.headers["Authorization"].removeprefix("Bearer ")
    assert jeton not in caplog.text
    assert "Bearer" not in caplog.text
