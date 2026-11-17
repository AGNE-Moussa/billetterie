"""Règles de la file d'attente, sans Redis (BIL-015 ; review, « À couvrir », point 4).

Position 1 pour le prochain admis, attente `ceil(position / taille) × intervalle`, entrée
idempotente, admission par vagues avec un jeton signé, le même à chaque lecture.
"""

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from commun.admission import verifier_admission
from file_attente.domaine.file import (
    FileIntrouvable,
    PositionIntrouvable,
    ReglesFile,
    StatutFile,
    entrer_file,
    estimer_attente,
    lire_position,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def regles(seance_sous_file: UUID, cle_admission: str) -> ReglesFile:
    return ReglesFile(
        seances_sous_file=frozenset({seance_sous_file}),
        taille_vague=2,
        intervalle_vagues=10.0,
        cle_signature=cle_admission,
    )


@pytest.mark.parametrize(
    ("position", "taille", "intervalle", "attendue"),
    [
        (1, 50, 10.0, 10),
        (50, 50, 10.0, 10),
        (51, 50, 10.0, 20),
        (100, 50, 10.0, 20),
        (101, 50, 10.0, 30),
        (1, 1, 10.0, 10),
        (3, 1, 10.0, 30),
        # Intervalle fractionnaire : arrondi à la seconde supérieure.
        (1, 50, 0.5, 1),
        (3, 1, 0.5, 2),
        (2, 1, 2.4, 5),
    ],
)
def test_l_attente_estimee_est_le_nombre_de_vagues_fois_l_intervalle(
    position: int, taille: int, intervalle: float, attendue: int
) -> None:
    assert estimer_attente(position, taille, intervalle) == attendue


async def test_les_entrants_recoivent_les_positions_un_deux_trois_et_leur_attente(
    file_memoire: Any, regles: ReglesFile, seance_sous_file: UUID
) -> None:
    positions = [
        await entrer_file(file_memoire, regles, seance_sous_file, sub)
        for sub in ("client-1", "client-2", "client-3")
    ]

    assert [(p.position, p.attente_estimee_secondes, entre) for p, entre in positions] == [
        (1, 10, True),
        (2, 10, True),
        (3, 20, True),
    ]
    for position, _ in positions:
        assert position.statut is StatutFile.EN_ATTENTE
        assert position.jeton_admission is None
        assert position.admission_expire_le is None
        assert position.seance_id == seance_sous_file


async def test_une_seconde_entree_garde_la_place_et_signale_qu_il_y_etait_deja(
    file_memoire: Any, regles: ReglesFile, seance_sous_file: UUID
) -> None:
    await entrer_file(file_memoire, regles, seance_sous_file, "client-1")
    await entrer_file(file_memoire, regles, seance_sous_file, "client-2")

    position, entre = await entrer_file(file_memoire, regles, seance_sous_file, "client-1")

    assert entre is False
    assert position.position == 1
    assert file_memoire.attente[seance_sous_file] == ["client-1", "client-2"]


async def test_une_seance_hors_liste_n_a_pas_de_file(file_memoire: Any, regles: ReglesFile) -> None:
    autre = uuid4()

    with pytest.raises(FileIntrouvable) as entree:
        await entrer_file(file_memoire, regles, autre, "client-1")
    with pytest.raises(FileIntrouvable) as lecture:
        await lire_position(file_memoire, regles, autre, "client-1")

    assert (entree.value.code, entree.value.statut) == ("QUEUE_NOT_FOUND", 404)
    assert (lecture.value.code, lecture.value.statut) == ("QUEUE_NOT_FOUND", 404)
    assert file_memoire.attente == {}


async def test_lire_la_position_de_qui_n_est_pas_entre_renvoie_queue_position_not_found(
    file_memoire: Any, regles: ReglesFile, seance_sous_file: UUID
) -> None:
    await entrer_file(file_memoire, regles, seance_sous_file, "client-1")

    with pytest.raises(PositionIntrouvable) as erreur:
        await lire_position(file_memoire, regles, seance_sous_file, "client-2")

    assert (erreur.value.code, erreur.value.statut) == ("QUEUE_POSITION_NOT_FOUND", 404)


async def test_apres_une_vague_les_suivants_avancent_d_autant(
    file_memoire: Any, regles: ReglesFile, seance_sous_file: UUID
) -> None:
    for sub in ("client-1", "client-2", "client-3"):
        await entrer_file(file_memoire, regles, seance_sous_file, sub)

    file_memoire.admettre(seance_sous_file, regles.taille_vague)
    position = await lire_position(file_memoire, regles, seance_sous_file, "client-3")

    assert (position.statut, position.position, position.attente_estimee_secondes) == (
        StatutFile.EN_ATTENTE,
        1,
        10,
    )


async def test_un_admis_recoit_le_meme_jeton_a_chaque_lecture_accepte_par_verifier_admission(
    file_memoire: Any, regles: ReglesFile, seance_sous_file: UUID, cle_admission: str
) -> None:
    await entrer_file(file_memoire, regles, seance_sous_file, "client-1")
    file_memoire.admettre(seance_sous_file, regles.taille_vague)

    premiere = await lire_position(file_memoire, regles, seance_sous_file, "client-1")
    seconde = await lire_position(file_memoire, regles, seance_sous_file, "client-1")
    rentree, entre = await entrer_file(file_memoire, regles, seance_sous_file, "client-1")

    assert premiere.statut is StatutFile.ADMIS
    assert (premiere.position, premiere.attente_estimee_secondes) == (None, None)
    assert premiere.jeton_admission is not None
    assert premiere.jeton_admission == seconde.jeton_admission == rentree.jeton_admission
    assert entre is False
    assert premiere.admission_expire_le == file_memoire.maintenant + timedelta(seconds=600)
    echeance = verifier_admission(
        premiere.jeton_admission,
        seance_id=seance_sous_file,
        sub="client-1",
        maintenant=file_memoire.maintenant,
        cle=cle_admission,
    )
    assert echeance == premiere.admission_expire_le
