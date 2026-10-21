"""Hooks de garantie de .claude/hooks/ (BIL-F19) : décisions et appels réels des scripts."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
HOOKS = RACINE / ".claude" / "hooks"
sys.path.insert(0, str(HOOKS))

import formater  # noqa: E402
import git_sur  # noqa: E402
import proteger_fichiers  # noqa: E402
import tests_rapides  # noqa: E402

BRANCHE = "feat/bil-001-catalogue"


def _lancer(
    script: str, entree: dict[str, object], projet: Path
) -> subprocess.CompletedProcess[str]:
    """Le script comme le lance Claude Code : JSON sur stdin, code de sortie, stderr."""
    return subprocess.run(
        [sys.executable, str(HOOKS / script)],
        input=json.dumps(entree),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(projet)},
        timeout=60,
    )


# --- Protection des fichiers ------------------------------------------------------------------


@pytest.mark.parametrize("nom", [".env", ".env.local", ".env.production"])
def test_env_est_toujours_refuse(nom: str) -> None:
    motif = proteger_fichiers.decision(nom, nom, BRANCHE, None)

    assert motif is not None and nom in motif  # CA1 : message clair, qui nomme le fichier


@pytest.mark.parametrize("nom", ["id_rsa", "cle.pem", "serveur.key", "secrets.json", "credentials"])
def test_un_fichier_de_secrets_est_refuse(nom: str) -> None:
    assert proteger_fichiers.decision(f"infra/{nom}", nom, BRANCHE, None) is not None


def test_env_example_reste_modifiable() -> None:
    assert proteger_fichiers.decision(".env.example", ".env.example", BRANCHE, None) is None


def test_sur_main_aucun_fichier_du_projet_ne_s_ecrit() -> None:
    assert "main" in str(proteger_fichiers.decision("README.md", "README.md", "main", None))
    # Hors du projet (mémoire de Claude, dossier temporaire) : permis.
    assert proteger_fichiers.decision(None, "notes.md", "main", None) is None


@pytest.mark.parametrize(
    "chemin",
    [
        "tests/unit/test_auth.py",
        "services/billets/tests/integration/test_places.py",
        "frontend/src/ecrans/Seance.test.tsx",
        "frontend/e2e/achat.spec.ts",
    ],
)
@pytest.mark.parametrize("etape", ["implementation", "review", "pr"])
def test_les_tests_sont_verrouilles_a_partir_de_l_implementation(chemin: str, etape: str) -> None:
    motif = proteger_fichiers.decision(chemin, Path(chemin).name, BRANCHE, etape)

    assert motif is not None and etape in motif  # CA2


@pytest.mark.parametrize("etape", [None, "cadrage", "plan", "tests"])
def test_les_tests_restent_modifiables_avant_l_implementation(etape: str | None) -> None:
    assert proteger_fichiers.decision("tests/unit/test_x.py", "test_x.py", BRANCHE, etape) is None


def test_le_code_reste_modifiable_pendant_l_implementation() -> None:
    chemin = "services/billets/src/billets/domaine/places.py"

    assert proteger_fichiers.decision(chemin, "places.py", BRANCHE, "implementation") is None


@pytest.mark.parametrize(
    ("etape", "permis"),
    [(None, True), ("contrat", True), ("plan", False), ("implementation", False)],
)
def test_le_contrat_ne_change_qu_a_l_etape_contrat(etape: str | None, permis: bool) -> None:
    motif = proteger_fichiers.decision("services/echo/openapi.yaml", "openapi.yaml", BRANCHE, etape)

    assert (motif is None) is permis


# --- Git sûr ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "commande",
    [
        "gh pr merge 21 --merge --delete-branch",
        "cd /c/projet && gh pr merge 21",
        "git push --force",
        "git push -f origin feat/x",
        "git push --force-with-lease origin feat/x",
        "git push origin +feat/x",
        "git push origin main",
        "git push origin HEAD:main",
        "git switch main && git merge feat/x",
        "echo SECRET=1 > .env",
        "echo SECRET=1 >> .env.local",
        "Set-Content -Path .env -Value 'SECRET=1'",
        "'x' | Out-File .env",
    ],
)
def test_commandes_refusees(commande: str) -> None:
    assert git_sur.decision(commande, BRANCHE) is not None  # CA3 : gh pr merge


def test_git_merge_est_refuse_quand_la_branche_courante_est_main() -> None:
    assert git_sur.decision("git merge feat/x", "main") is not None
    assert git_sur.decision("git merge main", BRANCHE) is None  # main dans la branche du ticket


@pytest.mark.parametrize(
    "commande",
    [
        "git push -u origin feat/bil-019-catalogue",
        "git push origin --delete chore/bil-f18-rules",
        "git switch main && git pull",
        "gh pr create --base main --title 'feat: x'",
        "gh pr view 21 --json state",
        "grep '^KEYCLOAK_SERVICES_SECRET=' .env | cut -d= -f2-",
        "cp .env.example .env.example.bak",
        "make test-unit 2>/dev/null",
    ],
)
def test_commandes_permises(commande: str) -> None:
    assert git_sur.decision(commande, BRANCHE) is None


@pytest.mark.parametrize(
    "commande",
    [
        "cat > tests/unit/test_x.py <<'EOF'",
        "echo 'def test_x(): pass' >> services/billets/tests/unit/test_x.py",
        "cp /tmp/test_x.py tests/unit/test_x.py",
        "'x' | Out-File frontend/src/Seance.test.tsx",
        "Set-Content -Path tests\\unit\\test_x.py -Value 'x'",
        "sed -i 's/assert/# assert/' tests/unit/test_auth.py",
    ],
)
def test_le_shell_ne_contourne_pas_le_verrou_des_tests(commande: str) -> None:
    assert git_sur.decision(commande, BRANCHE, "implementation") is not None  # CA2


@pytest.mark.parametrize(
    "commande",
    [
        "uv run pytest tests/unit > resultats.txt",
        "cat tests/unit/test_auth.py",
        "cp tests/unit/test_auth.py /tmp/copie.py",
        "make test-unit 2>&1 | tee sortie.log",
    ],
)
def test_lire_ou_lancer_les_tests_reste_permis_pendant_l_implementation(commande: str) -> None:
    assert git_sur.decision(commande, BRANCHE, "implementation") is None


def test_le_shell_ne_modifie_pas_le_contrat_hors_de_l_etape_contrat() -> None:
    commande = "echo 'openapi: 3.1.0' > services/echo/openapi.yaml"

    assert git_sur.decision(commande, BRANCHE, "plan") is not None
    assert git_sur.decision(commande, BRANCHE, "contrat") is None
    assert git_sur.decision(commande, BRANCHE, None) is None


# --- Formatage --------------------------------------------------------------------------------


def test_un_fichier_python_passe_par_ruff_format_puis_ruff_check(tmp_path: Path) -> None:
    commandes = [c for c, _ in formater.commandes("libs/commun/auth.py", tmp_path)]

    assert [c[-2:] for c in commandes] == [
        ["format", "libs/commun/auth.py"],
        ["check", "libs/commun/auth.py"],
    ]


def test_sans_outillage_front_rien_n_est_lance(tmp_path: Path) -> None:
    assert formater.commandes("frontend/src/App.tsx", tmp_path) == []
    assert formater.commandes("docs/workflow.md", tmp_path) == []


@pytest.mark.skipif(
    not (RACINE / "frontend" / "node_modules" / ".bin").is_dir(),
    reason="outillage du front non installé (npm install dans frontend/)",
)
def test_un_tsx_mal_formate_est_corrige_et_une_erreur_eslint_est_renvoyee() -> None:
    """CA4, avec les vrais Prettier et ESLint de frontend/."""
    fichier = RACINE / "frontend" / "src" / "essai_hook.tsx"
    fichier.parent.mkdir(exist_ok=True)
    try:
        fichier.write_text("const  x : any=1\nexport   const y=x\n", encoding="utf-8")
        resultat = _lancer("formater.py", {"tool_input": {"file_path": str(fichier)}}, RACINE)

        assert fichier.read_text(encoding="utf-8") == "const x: any = 1;\nexport const y = x;\n"
        assert resultat.returncode == 2
        assert "no-explicit-any" in resultat.stderr
    finally:
        fichier.unlink(missing_ok=True)
        if not any(fichier.parent.iterdir()):
            fichier.parent.rmdir()


# --- Tests rapides en fin de tour ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("fichiers", "suites"),
    [
        (["frontend/src/App.tsx"], ["vitest"]),
        (["libs/commun/auth.py"], ["pytest"]),
        (["libs/commun/auth.py", "frontend/src/App.tsx"], ["pytest", "vitest"]),
        (["docs/workflow.md", "frontend/CLAUDE.md"], []),
    ],
)
def test_seuls_les_tests_de_ce_qui_a_change_sont_lances(
    fichiers: list[str], suites: list[str]
) -> None:
    assert tests_rapides.a_lancer(fichiers) == suites  # CA5


def test_pytest_ne_lance_que_les_tests_unitaires() -> None:
    commande = tests_rapides.commande("pytest", RACINE)

    assert commande is not None
    assert "tests/unit" in commande
    assert not any("integration" in morceau for morceau in commande)


# --- Scripts lancés comme par Claude Code ------------------------------------------------------


def test_le_script_bloque_env_avec_le_code_2_et_un_message(tmp_path: Path) -> None:
    resultat = _lancer(
        "proteger_fichiers.py", {"tool_input": {"file_path": str(tmp_path / ".env")}}, tmp_path
    )

    assert resultat.returncode == 2
    assert ".env" in resultat.stderr


def test_le_script_git_sur_bloque_gh_pr_merge(tmp_path: Path) -> None:
    resultat = _lancer("git_sur.py", {"tool_input": {"command": "gh pr merge 21"}}, tmp_path)

    assert resultat.returncode == 2
    assert "merge est humain" in resultat.stderr


def test_une_commande_ordinaire_passe(tmp_path: Path) -> None:
    resultat = _lancer("git_sur.py", {"tool_input": {"command": "git status"}}, tmp_path)

    assert resultat.returncode == 0
    assert resultat.stderr == ""
