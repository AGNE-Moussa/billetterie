"""Agents de .claude/agents/ (BIL-F20) : outils et chemins d'écriture limités par leur hook."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[2]
AGENTS = RACINE / ".claude" / "agents"
HOOKS = RACINE / ".claude" / "hooks"
sys.path.insert(0, str(HOOKS))

import limiter_ecriture  # noqa: E402


def _entete(nom: str) -> dict[str, object]:
    texte = (AGENTS / f"{nom}.md").read_text(encoding="utf-8")
    entete: dict[str, object] = yaml.safe_load(texte.split("---\n", 2)[1])
    return entete


def _motifs_du_hook(nom: str) -> list[str]:
    """Motifs passés à limiter_ecriture.py dans le hook PreToolUse de l'agent."""
    hooks = _entete(nom)["hooks"]
    assert isinstance(hooks, dict)
    (regle,) = hooks["PreToolUse"]
    assert regle["matcher"] == "Write|Edit|NotebookEdit"
    (commande,) = regle["hooks"]
    assert "limiter_ecriture.py" in commande["command"]
    mots = shlex.split(commande["command"])
    return mots[mots.index(next(m for m in mots if m.endswith("limiter_ecriture.py"))) + 1 :]


@pytest.mark.parametrize(
    ("nom", "outils", "motifs"),
    [
        ("test-planner", "Read, Grep, Glob, Write", ["docs/test-plans/*.md"]),
        ("contract-writer", "Read, Grep, Glob, Write, Edit", ["services/*/openapi.yaml"]),
    ],
)
def test_l_agent_n_a_que_ses_outils_et_ses_chemins(
    nom: str, outils: str, motifs: list[str]
) -> None:
    entete = _entete(nom)

    assert entete["name"] == nom
    assert entete["tools"] == outils  # ni Bash ni PowerShell : aucune écriture par le shell
    assert _motifs_du_hook(nom) == motifs


@pytest.mark.parametrize(
    ("chemin", "permis"),
    [
        ("docs/test-plans/BIL-006.md", True),
        ("docs/test-plans/sous-dossier/BIL-006.md", False),
        ("docs/test-plans/BIL-006.txt", False),
        ("tests/unit/test_places.py", False),
        ("docs/tickets/BIL-006.md", False),
        (None, False),
    ],
)
def test_test_planner_n_ecrit_que_dans_docs_test_plans(chemin: str | None, permis: bool) -> None:
    assert limiter_ecriture.autorise(chemin, ["docs/test-plans/*.md"]) is permis  # CA2


@pytest.mark.parametrize(
    ("chemin", "permis"),
    [
        ("services/billets/openapi.yaml", True),
        ("services/echo/openapi.yaml", True),
        ("services/billets/src/billets/api/routes.py", False),
        ("services/billets/v2/openapi.yaml", False),
        ("openapi.yaml", False),
    ],
)
def test_contract_writer_n_ecrit_que_les_contrats(chemin: str, permis: bool) -> None:
    assert limiter_ecriture.autorise(chemin, ["services/*/openapi.yaml"]) is permis  # CA4


def test_le_hook_refuse_avec_le_code_2_et_nomme_l_agent(tmp_path: Path) -> None:
    entree = {
        "agent_type": "test-planner",
        "tool_input": {"file_path": str(tmp_path / "tests" / "unit" / "test_x.py")},
    }
    resultat = subprocess.run(
        [sys.executable, str(HOOKS / "limiter_ecriture.py"), "docs/test-plans/*.md"],
        input=json.dumps(entree),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)},
        timeout=60,
    )

    assert resultat.returncode == 2
    assert "test-planner n'écrit que dans docs/test-plans/*.md" in resultat.stderr
