"""CA3 (BIL-006, décision Q2) : seul le détenteur lève le verrou, dans un vrai Redis.

Pas de route de libération : la libération compare-puis-supprime est une fonction du magasin
de verrous (`billets.infra.verrous.VerrousRedis.liberer`). Côté HTTP, une confirmation
demandée par une autre commande répond 409.
"""

import asyncio
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from typing import Any

import pytest

from billets.infra.verrous import VerrousRedis

pytestmark = pytest.mark.anyio

DELAI_REDIS = 0.5
ATTENTE_EXPIRATION = 2.5
TOURS = 100
# Durée du verrou de commande_a à chaque tour (plan : 5 ms).
DUREE_COURTE_MS = 5
# Durée du verrou de commande_b, largement au-delà d'un tour.
DUREE_LONGUE_MS = 60_000
# Échéance d'un tour pour que commande_b obtienne le verrou.
ECHEANCE_TOUR = 2.0
# Libérations de commande_a encore tentées après le succès de commande_b.
LIBERATIONS_APRES_SUCCES = 20
CONFIRMATIONS = 10


@pytest.fixture
async def verrous(redis_url: str) -> AsyncIterator[VerrousRedis]:
    magasin = VerrousRedis(redis_url, DELAI_REDIS)
    try:
        yield magasin
    finally:
        await magasin.fermer()


async def test_le_detenteur_libere_son_verrou(
    plateforme: Any, seance: Any, observateur: Any, verrous: VerrousRedis, outils: Any
) -> None:
    place = seance.places["A1"]
    commande_a = uuid.uuid4()
    outils.exiger_statut(
        await plateforme.verrouiller(seance.id, place, commande_a), 200, "verrou de commande_a"
    )

    libere = await verrous.liberer(seance.id, place, commande_a)

    assert libere is True
    assert await observateur.valeur(outils.cle_verrou(seance.id, place)) is None
    outils.exiger_statut(
        await plateforme.verrouiller(seance.id, place, uuid.uuid4()),
        200,
        "commande_b après libération",
    )


async def test_une_autre_commande_ne_libere_pas_le_verrou(
    plateforme: Any, seance: Any, observateur: Any, verrous: VerrousRedis, outils: Any
) -> None:
    place = seance.places["A1"]
    cle = outils.cle_verrou(seance.id, place)
    commande_a = uuid.uuid4()
    outils.exiger_statut(
        await plateforme.verrouiller(seance.id, place, commande_a), 200, "verrou de commande_a"
    )
    pttl_avant = await observateur.pttl(cle)

    libere = await verrous.liberer(seance.id, place, uuid.uuid4())

    assert libere is False
    assert await observateur.valeur(cle) == str(commande_a)
    assert abs(await observateur.pttl(cle) - pttl_avant) <= 1_000


async def test_liberer_une_place_sans_verrou_ne_fait_rien(
    observateur: Any, verrous: VerrousRedis
) -> None:
    seance_id, place_id = uuid.uuid4(), uuid.uuid4()

    libere = await verrous.liberer(seance_id, place_id, uuid.uuid4())

    assert libere is False
    assert await observateur.cles() == []


async def test_un_ancien_detenteur_ne_libere_pas_le_verrou_pris_apres_expiration(
    plateforme_courte: Any, seance: Any, observateur: Any, verrous: VerrousRedis, outils: Any
) -> None:
    place = seance.places["A1"]
    commande_a, commande_b = uuid.uuid4(), uuid.uuid4()
    outils.exiger_statut(
        await plateforme_courte.verrouiller(seance.id, place, commande_a), 200, "verrou de a"
    )
    await asyncio.sleep(ATTENTE_EXPIRATION)
    outils.exiger_statut(
        await plateforme_courte.verrouiller(seance.id, place, commande_b), 200, "verrou de b"
    )

    libere = await verrous.liberer(seance.id, place, commande_a)

    assert libere is False
    assert await observateur.valeur(outils.cle_verrou(seance.id, place)) == str(commande_b)


async def _tour(verrous: VerrousRedis, observateur: Any, outils: Any, numero: int) -> None:
    """Un tour : verrou de commande_a à 5 ms, puis libérations de a et verrouillages de b en
    parallèle. Dès que b a obtenu le verrou, la clé doit valoir b jusqu'à la fin du tour."""
    seance_id, place_id = uuid.uuid4(), uuid.uuid4()
    cle = outils.cle_verrou(seance_id, place_id)
    commande_a, commande_b = uuid.uuid4(), uuid.uuid4()
    await verrous.poser(seance_id, place_id, commande_a, DUREE_COURTE_MS)
    obtenu = asyncio.Event()
    valeurs_apres_succes: list[str | None] = []

    async def liberer_a() -> None:
        restantes = LIBERATIONS_APRES_SUCCES
        limite = time.monotonic() + ECHEANCE_TOUR
        while time.monotonic() < limite and restantes > 0:
            await verrous.liberer(seance_id, place_id, commande_a)
            if obtenu.is_set():
                restantes -= 1
                valeurs_apres_succes.append(await observateur.valeur(cle))

    async def verrouiller_b() -> None:
        limite = time.monotonic() + ECHEANCE_TOUR
        while time.monotonic() < limite:
            if await verrous.poser(seance_id, place_id, commande_b, DUREE_LONGUE_MS) is not None:
                obtenu.set()
                return
            await asyncio.sleep(0)

    await asyncio.gather(liberer_a(), verrouiller_b())

    assert obtenu.is_set(), (
        f"tour {numero} : commande_b n'a jamais obtenu le verrou en {ECHEANCE_TOUR:.0f} s"
    )
    assert set(valeurs_apres_succes) <= {str(commande_b)}, (
        f"tour {numero} : verrou de commande_b supprimé par commande_a : {valeurs_apres_succes}"
    )
    assert await observateur.valeur(cle) == str(commande_b), f"tour {numero}"
    await observateur.supprimer(cle)


async def test_des_liberations_concurrentes_d_un_ancien_detenteur_ne_suppriment_jamais_le_verrou_d_un_autre(  # noqa: E501 : nom du plan
    observateur: Any, verrous: VerrousRedis, outils: Any
) -> None:
    for numero in range(TOURS):
        await _tour(verrous, observateur, outils, numero)


async def test_des_confirmations_simultanees_seul_le_detenteur_l_obtient(
    plateforme: Any, seance: Any, observateur: Any, outils: Any
) -> None:
    place = seance.places["A1"]
    cle = outils.cle_verrou(seance.id, place)
    commande_a = uuid.uuid4()
    outils.exiger_statut(
        await plateforme.verrouiller(seance.id, place, commande_a), 200, "verrou de commande_a"
    )
    commandes = [commande_a] * CONFIRMATIONS + [uuid.uuid4() for _ in range(CONFIRMATIONS)]

    reponses = await outils.borne(
        f"{2 * CONFIRMATIONS} confirmations simultanées",
        asyncio.gather(
            *(
                plateforme.verrouiller(
                    seance.id,
                    place,
                    commande,
                    confirmation=True,
                    client=plateforme.instance(numero),
                )
                for numero, commande in enumerate(commandes)
            )
        ),
    )

    du_detenteur = Counter(r.status_code for r in reponses[:CONFIRMATIONS])
    des_autres = Counter(r.status_code for r in reponses[CONFIRMATIONS:])
    assert du_detenteur == {200: CONFIRMATIONS}, du_detenteur
    assert des_autres == {409: CONFIRMATIONS}, des_autres
    assert {r.json()["code"] for r in reponses[CONFIRMATIONS:]} == {"SEAT_ALREADY_TAKEN"}
    assert await observateur.valeur(cle) == str(commande_a)
    duree_ms = plateforme.duree_confirmation * 1_000
    assert duree_ms - 5_000 <= await observateur.pttl(cle) <= duree_ms
