"""Configuration de file-attente (BIL-015 ; review, « À couvrir », point 3).

SEANCES_SOUS_FILE (liste séparée par des virgules), clé d'admission exigée dès qu'une séance est
sous file, taille et rythme des vagues, durée d'admission de 10 min par défaut.
"""

import secrets
from uuid import uuid4

import pytest
from pydantic import ValidationError

from commun.admission import LONGUEUR_MIN_CLE
from file_attente.config import Parametres


def test_par_defaut_aucune_seance_n_est_sous_file_et_les_vagues_ont_leurs_valeurs_par_defaut(
    environnement_propre: None,
) -> None:
    config = Parametres()

    assert config.seances_sous_file == frozenset()
    assert config.admission_cle_signature.get_secret_value() == ""
    assert (config.taille_vague, config.intervalle_vagues, config.duree_admission) == (
        50,
        10.0,
        600,
    )


def test_les_seances_sous_file_se_lisent_avec_espaces_et_entrees_vides(
    monkeypatch: pytest.MonkeyPatch, environnement_propre: None
) -> None:
    premiere, seconde = uuid4(), uuid4()
    monkeypatch.setenv("SEANCES_SOUS_FILE", f" {premiere} ,, {seconde},")
    monkeypatch.setenv("ADMISSION_CLE_SIGNATURE", secrets.token_urlsafe(48))

    assert Parametres().seances_sous_file == frozenset({premiere, seconde})


def test_une_liste_vide_ne_met_aucune_seance_sous_file(
    monkeypatch: pytest.MonkeyPatch, environnement_propre: None
) -> None:
    monkeypatch.setenv("SEANCES_SOUS_FILE", "")

    assert Parametres().seances_sous_file == frozenset()


def test_un_identifiant_de_seance_invalide_est_refuse(
    monkeypatch: pytest.MonkeyPatch, environnement_propre: None
) -> None:
    monkeypatch.setenv("SEANCES_SOUS_FILE", f"{uuid4()},pas-un-uuid")
    monkeypatch.setenv("ADMISSION_CLE_SIGNATURE", secrets.token_urlsafe(48))

    with pytest.raises(ValidationError):
        Parametres()


@pytest.mark.parametrize("cle", [None, "c" * (LONGUEUR_MIN_CLE - 1)])
def test_une_seance_sous_file_sans_cle_ou_avec_une_cle_courte_refuse_le_demarrage(
    monkeypatch: pytest.MonkeyPatch, environnement_propre: None, cle: str | None
) -> None:
    monkeypatch.setenv("SEANCES_SOUS_FILE", str(uuid4()))
    if cle is not None:
        monkeypatch.setenv("ADMISSION_CLE_SIGNATURE", cle)

    with pytest.raises(ValidationError, match="ADMISSION_CLE_SIGNATURE"):
        Parametres()


def test_sans_seance_sous_file_la_cle_n_est_pas_exigee(environnement_propre: None) -> None:
    assert Parametres(admission_cle_signature="courte").seances_sous_file == frozenset()


def test_les_vagues_et_la_duree_d_admission_se_lisent_dans_l_environnement(
    monkeypatch: pytest.MonkeyPatch, environnement_propre: None
) -> None:
    monkeypatch.setenv("TAILLE_VAGUE", "5")
    monkeypatch.setenv("INTERVALLE_VAGUES", "2.5")
    monkeypatch.setenv("DUREE_ADMISSION", "120")

    config = Parametres()

    assert (config.taille_vague, config.intervalle_vagues, config.duree_admission) == (5, 2.5, 120)


@pytest.mark.parametrize(
    ("variable", "valeur"),
    [
        ("TAILLE_VAGUE", "0"),
        ("INTERVALLE_VAGUES", "0"),
        ("DUREE_ADMISSION", "0"),
        ("DELAI_REDIS", "0"),
    ],
)
def test_une_valeur_nulle_des_vagues_ou_des_delais_est_refusee(
    monkeypatch: pytest.MonkeyPatch, environnement_propre: None, variable: str, valeur: str
) -> None:
    monkeypatch.setenv(variable, valeur)

    with pytest.raises(ValidationError):
        Parametres()


def test_la_cle_d_admission_n_apparait_pas_dans_la_representation(
    monkeypatch: pytest.MonkeyPatch, environnement_propre: None
) -> None:
    cle = secrets.token_urlsafe(48)
    monkeypatch.setenv("SEANCES_SOUS_FILE", str(uuid4()))
    monkeypatch.setenv("ADMISSION_CLE_SIGNATURE", cle)

    config = Parametres()

    assert cle not in repr(config)
    assert cle not in str(config.model_dump())
