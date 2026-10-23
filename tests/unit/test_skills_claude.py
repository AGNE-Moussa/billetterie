"""Skills de .claude/skills/ (BIL-F23, BIL-F24) : en-têtes lisibles et règles qui ne bougent pas."""

from pathlib import Path

import pytest
import yaml

SKILLS = Path(__file__).resolve().parents[2] / ".claude" / "skills"
ATTENDUS = {"ticket", "write-tests", "open-pr", "smoke-tests"}


def _texte(nom: str) -> str:
    return (SKILLS / nom / "SKILL.md").read_text(encoding="utf-8")


def test_les_skills_prevus_existent() -> None:
    assert {d.name for d in SKILLS.iterdir() if (d / "SKILL.md").is_file()} == ATTENDUS


@pytest.mark.parametrize("nom", sorted(ATTENDUS))
def test_chaque_skill_a_un_en_tete_lisible(nom: str) -> None:
    entete = yaml.safe_load(_texte(nom).split("---\n", 2)[1])

    assert entete["name"] == nom
    assert entete["description"]


@pytest.mark.parametrize("nom", sorted(ATTENDUS))
def test_aucun_skill_ne_merge(nom: str) -> None:
    """CA3 : le mot « merge » n'apparaît que pour dire qu'il est humain ou interdit."""
    for ligne in _texte(nom).lower().splitlines():
        if "merge" in ligne:
            assert any(mot in ligne for mot in ("jamais", "humain", "lui-même", "bloque")), ligne


def test_write_tests_refuse_un_plan_non_valide_et_lance_en_parallele() -> None:
    texte = _texte("write-tests")

    assert "**arrête-toi**" in texte  # questions encore ouvertes
    assert "**en parallèle, dans le même message**" in texte  # CA1
    assert "**n'est pas lancé**" in texte  # niveau absent du plan


def test_open_pr_refuse_des_tests_rouges_et_passe_en_review() -> None:
    texte = _texte("open-pr")

    assert "## 1. Refuser si quelque chose est rouge" in texte
    assert "**avec l'ID du ticket**" in texte
    assert "`IN REVIEW`" in texte
    assert "Tu ne poses jamais `TO TEST` ni `✅ DONE`." in texte


def test_les_smoke_tests_sont_exclus_des_tests_ordinaires() -> None:
    pyproject = (SKILLS.parents[1] / "pyproject.toml").read_text(encoding="utf-8")

    assert "-m 'not smoke'" in pyproject
    assert "pytest.mark.smoke" in _texte("smoke-tests")


def test_write_tests_ne_rend_aucun_resultat_sans_mesure() -> None:
    """Essai de BIL-F24 : une session a rendu des tests « rouges » qui n'existaient pas."""
    texte = _texte("write-tests")

    assert "**Aucun résultat sans mesure.**" in texte
    assert "relis le fichier" in texte  # marqueur réellement écrit, sinon arrêt


def test_le_marqueur_est_hors_de_claude() -> None:
    """Claude Code refuse d'écrire un fichier de .claude/ sans permission, même autorisé."""
    for nom in ATTENDUS:
        assert ".claude/etape" not in _texte(nom), nom
        assert ".pipeline/etape" in _texte(nom) or nom == "smoke-tests"
