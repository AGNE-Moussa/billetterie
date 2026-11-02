"""CA2 et E1 (BIL-006) : expiration, prolongation et confirmation du verrou dans un vrai Redis.

Durées courtes du plan : réservation 2 s, confirmation 4 s (`plateforme_courte`) ; les autres
cas gardent les durées par défaut (600 s et 3600 s, décision Q8).
"""

import asyncio
import uuid
from collections import Counter
from typing import Any

import pytest

pytestmark = pytest.mark.anyio

# Au-delà de la durée de réservation courte (2 s).
ATTENTE_EXPIRATION = 2.5
COMMANDES_APRES_EXPIRATION = 20
APPELS_MEME_COMMANDE = 10


async def test_le_verrou_expire_seul_dans_redis_sans_aucun_appel(
    plateforme_courte: Any, seance: Any, observateur: Any, outils: Any
) -> None:
    place = seance.places["A1"]
    cle = outils.cle_verrou(seance.id, place)
    verrou = await plateforme_courte.verrouiller(seance.id, place, uuid.uuid4())
    outils.exiger_statut(verrou, 200, "verrou de commande_a")

    await asyncio.sleep(ATTENTE_EXPIRATION)

    assert await observateur.valeur(cle) is None
    disponibilites = await plateforme_courte.disponibilites(seance.id)
    assert disponibilites[str(place)] is True
    commande_b = await plateforme_courte.verrouiller(
        seance.id, place, uuid.uuid4(), client=plateforme_courte.instance_2
    )
    outils.exiger_statut(commande_b, 200, "commande_b après expiration")


async def test_le_verrou_confirme_dure_la_duree_de_confirmation(
    plateforme_courte: Any, seance: Any, observateur: Any, outils: Any
) -> None:
    place = seance.places["A1"]
    cle = outils.cle_verrou(seance.id, place)
    commande_a = uuid.uuid4()
    outils.exiger_statut(
        await plateforme_courte.verrouiller(seance.id, place, commande_a), 200, "verrou"
    )
    outils.exiger_statut(
        await plateforme_courte.verrouiller(seance.id, place, commande_a, confirmation=True),
        200,
        "confirmation par commande_a",
    )

    await asyncio.sleep(3)
    a_trois_secondes = await plateforme_courte.verrouiller(seance.id, place, uuid.uuid4())
    outils.exiger_probleme(a_trois_secondes, 409, "SEAT_ALREADY_TAKEN", "commande_b à 3 s")

    await asyncio.sleep(1.5)
    assert await observateur.valeur(cle) is None
    a_quatre_secondes_et_demie = await plateforme_courte.verrouiller(seance.id, place, uuid.uuid4())
    outils.exiger_statut(a_quatre_secondes_et_demie, 200, "commande_b à 4,5 s")


async def test_apres_expiration_plusieurs_commandes_simultanees_n_ont_qu_un_gagnant(
    plateforme_courte: Any, seance: Any, outils: Any
) -> None:
    place = seance.places["A1"]
    outils.exiger_statut(
        await plateforme_courte.verrouiller(seance.id, place, uuid.uuid4()), 200, "verrou"
    )
    await asyncio.sleep(ATTENTE_EXPIRATION)

    reponses = await outils.borne(
        f"{COMMANDES_APRES_EXPIRATION} PUT simultanés après expiration",
        asyncio.gather(
            *(
                plateforme_courte.verrouiller(
                    seance.id, place, uuid.uuid4(), client=plateforme_courte.instance(numero)
                )
                for numero in range(COMMANDES_APRES_EXPIRATION)
            )
        ),
    )

    statuts = Counter(reponse.status_code for reponse in reponses)
    assert statuts == {200: 1, 409: COMMANDES_APRES_EXPIRATION - 1}, statuts


async def test_la_prolongation_dans_redis_repose_l_expiration_sans_changer_la_valeur(
    plateforme_courte: Any, seance: Any, observateur: Any, outils: Any
) -> None:
    place = seance.places["A1"]
    cle = outils.cle_verrou(seance.id, place)
    commande_a = uuid.uuid4()
    outils.exiger_statut(
        await plateforme_courte.verrouiller(seance.id, place, commande_a), 200, "verrou"
    )

    await asyncio.sleep(1.5)
    prolongation = await plateforme_courte.verrouiller(
        seance.id, place, commande_a, client=plateforme_courte.instance_2
    )
    outils.exiger_statut(prolongation, 200, "nouvel appel de commande_a à 1,5 s")
    await asyncio.sleep(1)

    assert await observateur.valeur(cle) == str(commande_a)
    assert 500 <= await observateur.pttl(cle) <= 1_100


async def test_dix_appels_simultanes_de_la_meme_commande_renvoient_tous_200(
    plateforme: Any, seance: Any, observateur: Any, outils: Any
) -> None:
    place = seance.places["A1"]
    commande_a = uuid.uuid4()

    reponses = await outils.borne(
        f"{APPELS_MEME_COMMANDE} PUT simultanés de la même commande",
        asyncio.gather(
            *(
                plateforme.verrouiller(
                    seance.id, place, commande_a, client=plateforme.instance(numero)
                )
                for numero in range(APPELS_MEME_COMMANDE)
            )
        ),
    )

    statuts = Counter(reponse.status_code for reponse in reponses)
    assert statuts == {200: APPELS_MEME_COMMANDE}, statuts
    assert await observateur.cles() == [outils.cle_verrou(seance.id, place)]
    assert await observateur.valeur(outils.cle_verrou(seance.id, place)) == str(commande_a)


async def test_la_confirmation_d_un_verrou_expire_renvoie_409(
    plateforme_courte: Any, seance: Any, observateur: Any, outils: Any
) -> None:
    place = seance.places["A1"]
    commande_a = uuid.uuid4()
    outils.exiger_statut(
        await plateforme_courte.verrouiller(seance.id, place, commande_a), 200, "verrou"
    )
    await asyncio.sleep(ATTENTE_EXPIRATION)

    reponse = await plateforme_courte.verrouiller(seance.id, place, commande_a, confirmation=True)

    outils.exiger_probleme(reponse, 409, "SEAT_ALREADY_TAKEN", "confirmation d'un verrou expiré")
    assert await observateur.cles() == []
