"""BIL-015 : file d'attente virtuelle avec un vrai Redis (review, « À couvrir », point 6).

Entrée idempotente sous concurrence, positions distinctes, vagues sans perte ni doublon, une
seule vague par intervalle entre deux instances (verrou Redis), expiration de l'admission, et
Redis injoignable (503 FILE_INDISPONIBLE).
"""

import asyncio
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import anyio
import pytest

from commun.admission import verifier_admission
from file_attente.infra.file_redis import FileRedis, cle_attente

pytestmark = pytest.mark.anyio

DELAI = 60.0


async def _ensemble(*attentes: Any) -> list[Any]:
    """Lance les appels ensemble (asyncio.gather), au plus DELAI secondes."""
    with anyio.fail_after(DELAI):
        return list(await asyncio.gather(*attentes))


def _probleme(reponse: Any, statut: int, code: str, etape: str) -> None:
    assert reponse.status_code == statut, f"{etape} : {reponse.status_code} {reponse.text}"
    assert reponse.headers["content-type"].startswith("application/problem+json"), etape
    assert reponse.json()["code"] == code, f"{etape} : {reponse.text}"


async def test_entrees_simultanees_du_meme_client_ne_creent_qu_une_entree(
    salle: Any, observateur: Any
) -> None:
    reponses = await _ensemble(*(salle.entrer("client-unique") for _ in range(10)))

    statuts = Counter(r.status_code for r in reponses)
    assert statuts == {201: 1, 200: 9}, [r.text for r in reponses]
    assert {r.json()["position"] for r in reponses} == {1}
    assert await observateur.membres(cle_attente(salle.seance_id)) == ["client-unique"]


async def test_des_clients_simultanes_ont_des_positions_distinctes_dans_la_file(
    salle: Any, observateur: Any
) -> None:
    subs = [f"client-{numero:02d}" for numero in range(20)]

    reponses = await _ensemble(*(salle.entrer(sub) for sub in subs))

    assert [r.status_code for r in reponses] == [201] * 20, [r.text for r in reponses]
    assert all(r.json()["statut"] == "EN_ATTENTE" for r in reponses)
    assert sorted(await observateur.membres(cle_attente(salle.seance_id))) == subs
    lues = sorted([(await salle.lire(sub)).json()["position"] for sub in subs])
    assert lues == list(range(1, 21))


async def test_les_positions_rendues_a_l_entree_sont_distinctes_et_suivent_l_arrivee(
    salle: Any, observateur: Any
) -> None:
    # Sujets dans l'ordre lexicographique inverse de l'ordre d'envoi : à milliseconde égale,
    # un arrivant plus tardif ne doit pas passer devant un client déjà entré.
    subs = [f"client-{numero:02d}" for numero in range(20, 0, -1)]

    reponses = await _ensemble(*(salle.entrer(sub) for sub in subs))

    rendues = {sub: r.json()["position"] for sub, r in zip(subs, reponses, strict=True)}
    assert sorted(rendues.values()) == list(range(1, 21)), rendues
    membres = await observateur.membres(cle_attente(salle.seance_id))
    assert [rendues[sub] for sub in membres] == list(range(1, 21)), (membres, rendues)


async def test_une_vague_admet_les_premiers_entres_sans_perte_ni_doublon(salle: Any) -> None:
    subs = [f"client-{numero}" for numero in range(5)]
    for sub in subs:
        assert (await salle.entrer(sub)).status_code == 201, sub
    tache = salle.tache(intervalle=0.2)
    admis_par_vague: list[list[str]] = []

    for _ in range(3):
        assert await tache.cycle() is True
        lectures = {sub: (await salle.lire(sub)).json() for sub in subs}
        admis = [s for s in subs if lectures[s]["statut"] == "ADMIS"]
        admis_par_vague.append(admis)
        attente = [s for s in subs if lectures[s]["statut"] == "EN_ATTENTE"]
        assert [lectures[s]["position"] for s in attente] == list(range(1, len(attente) + 1))
        await asyncio.sleep(0.3)  # verrou de la tâche (intervalle 0,2 s) expiré

    assert admis_par_vague == [subs[:2], subs[:4], subs]


async def test_un_admis_recoit_le_meme_jeton_valable_a_chaque_lecture(salle: Any) -> None:
    await salle.entrer("client-admis")
    assert await salle.tache().cycle() is True

    lectures = [(await salle.lire("client-admis")).json() for _ in range(3)]
    reentree = await salle.entrer("client-admis")

    assert reentree.status_code == 200
    jetons = {lecture["jeton_admission"] for lecture in lectures} | {
        reentree.json()["jeton_admission"]
    }
    assert len(jetons) == 1 and None not in jetons, lectures
    assert lectures[0]["statut"] == "ADMIS"
    assert lectures[0]["position"] is None
    echeance = verifier_admission(
        jetons.pop(),
        seance_id=salle.seance_id,
        sub="client-admis",
        maintenant=datetime.now(UTC),
        cle=salle.cle,
    )
    attendue = datetime.fromisoformat(lectures[0]["admission_expire_le"])
    assert abs((echeance - attendue).total_seconds()) < 1


async def test_deux_instances_ne_font_qu_une_vague_par_intervalle(
    salle: Any, redis_url: str
) -> None:
    for numero in range(10):
        assert (await salle.entrer(f"client-{numero}")).status_code == 201
    files = [FileRedis(redis_url, 0.5) for _ in range(2)]
    try:
        taches = [
            salle.tache(file=file, instance=f"file-attente-{n}", taille=3, intervalle=5.0)
            for n, file in enumerate(files, start=1)
        ]

        resultats = await _ensemble(*(tache.cycle() for tache in taches))
        relance = await _ensemble(*(tache.cycle() for tache in taches))
    finally:
        for file in files:
            await file.fermer()

    assert sorted(resultats) == [False, True]
    assert relance == [False, False]
    statuts = Counter([(await salle.lire(f"client-{n}")).json()["statut"] for n in range(10)])
    assert statuts == {"ADMIS": 3, "EN_ATTENTE": 7}


async def test_une_admission_expiree_sort_de_la_file_et_une_nouvelle_entree_repart_en_fin(
    demarrer_file: Any,
) -> None:
    async with demarrer_file(taille_vague=1, duree_admission=1) as salle:
        await salle.entrer("client-a")
        await salle.entrer("client-b")
        assert await salle.tache().cycle() is True
        assert (await salle.lire("client-a")).json()["statut"] == "ADMIS"

        await asyncio.sleep(1.5)

        _probleme(
            await salle.lire("client-a"), 404, "QUEUE_POSITION_NOT_FOUND", "admission expirée"
        )
        reentree = await salle.entrer("client-a")
        assert reentree.status_code == 201, reentree.text
        assert reentree.json()["statut"] == "EN_ATTENTE"
        assert reentree.json()["position"] == 2
        assert (await salle.lire("client-b")).json()["position"] == 1


async def test_redis_injoignable_donne_503_file_indisponible(demarrer_file: Any) -> None:
    # Port fermé : aucune connexion possible, sans dépendre du conteneur du module.
    async with demarrer_file(redis_url="redis://127.0.0.1:1/0", delai_redis=0.5) as salle:
        _probleme(await salle.entrer("client-a"), 503, "FILE_INDISPONIBLE", "entrerFile")
        _probleme(await salle.lire("client-a"), 503, "FILE_INDISPONIBLE", "lirePositionFile")
        sante = await salle.client.get("/health")
        assert sante.status_code == 503, sante.text
