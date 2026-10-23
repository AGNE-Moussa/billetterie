"""Agents de .claude/agents/ (BIL-F20, BIL-F21) : outils, chemins et commandes limités par hook."""

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

import limiter_commandes  # noqa: E402
import limiter_ecriture  # noqa: E402

ECRITURE_UNITAIRE = [
    "tests/unit/**",
    "services/*/tests/unit/**",
    "infra/*/tests/unit/**",
    "frontend/src/**/*.test.tsx",
    "frontend/src/**/*.test.ts",
]
ECRITURE_INTEGRATION = [
    "tests/integration/**",
    "services/*/tests/integration/**",
    "services/*/tests/contract/**",
    "infra/*/tests/integration/**",
    "frontend/e2e/**",
]


def _entete(nom: str) -> dict[str, object]:
    texte = (AGENTS / f"{nom}.md").read_text(encoding="utf-8")
    entete: dict[str, object] = yaml.safe_load(texte.split("---\n", 2)[1])
    return entete


def _arguments_du_hook(nom: str, script: str, matcher: str) -> list[str]:
    """Arguments passés à `script` par le hook PreToolUse `matcher` de l'agent."""
    hooks = _entete(nom)["hooks"]
    assert isinstance(hooks, dict)
    (regle,) = [r for r in hooks["PreToolUse"] if script in r["hooks"][0]["command"]]
    assert regle["matcher"] == matcher
    mots = shlex.split(regle["hooks"][0]["command"])
    return mots[mots.index(next(m for m in mots if m.endswith(script))) + 1 :]


def _motifs_du_hook(nom: str) -> list[str]:
    return _arguments_du_hook(nom, "limiter_ecriture.py", "Write|Edit|NotebookEdit")


@pytest.mark.parametrize(
    ("nom", "outils", "motifs"),
    [
        ("test-planner", "Read, Grep, Glob, Write", ["docs/test-plans/*.md"]),
        (
            "contract-writer",
            "Read, Grep, Glob, Write, Edit",
            ["services/*/openapi.yaml", "docs/conventions.md"],  # BIL-F25 : formes communes
        ),
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


# --- Écrivains de tests (BIL-F21) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("nom", "motifs"),
    [("unit-test-writer", ECRITURE_UNITAIRE), ("integration-test-writer", ECRITURE_INTEGRATION)],
)
def test_chaque_ecrivain_de_tests_a_ses_dossiers(nom: str, motifs: list[str]) -> None:
    entete = _entete(nom)

    assert entete["name"] == nom
    assert entete["tools"] == "Read, Grep, Glob, Write, Edit, Bash"
    assert _motifs_du_hook(nom) == motifs


@pytest.mark.parametrize(
    ("chemin", "unitaire", "integration"),
    [
        ("tests/unit/test_auth.py", True, False),
        ("services/billets/tests/unit/test_places.py", True, False),
        ("services/billets/tests/unit/conftest.py", True, False),
        ("frontend/src/ecrans/catalogue/Catalogue.test.tsx", True, False),
        ("services/billets/tests/integration/test_verrou.py", False, True),
        ("services/billets/tests/contract/test_contrat_billets.py", False, True),
        ("frontend/e2e/catalogue.spec.ts", False, True),
        ("services/billets/src/billets/domaine/places.py", False, False),
        ("services/billets/openapi.yaml", False, False),
        ("frontend/src/ecrans/catalogue/Catalogue.tsx", False, False),
        ("docs/test-plans/BIL-006.md", False, False),
    ],
)
def test_chaque_ecrivain_n_ecrit_que_dans_ses_dossiers(
    chemin: str, unitaire: bool, integration: bool
) -> None:
    assert limiter_ecriture.autorise(chemin, ECRITURE_UNITAIRE) is unitaire  # CA1
    assert limiter_ecriture.autorise(chemin, ECRITURE_INTEGRATION) is integration  # CA1


def test_seul_l_ecrivain_d_integration_peut_lancer_docker() -> None:
    unitaire = _arguments_du_hook("unit-test-writer", "limiter_commandes.py", "Bash|PowerShell")
    integration = _arguments_du_hook(
        "integration-test-writer", "limiter_commandes.py", "Bash|PowerShell"
    )

    assert limiter_commandes.decision("docker compose up -d", unitaire) is not None
    assert limiter_commandes.decision("make test-integration", unitaire) is not None
    assert limiter_commandes.decision("docker compose up -d", integration) is None
    for permises in (unitaire, integration):
        assert limiter_commandes.decision("uv run pytest tests/unit -q", permises) is None


@pytest.mark.parametrize(
    "commande",
    [
        "uv run pytest tests/unit > rapport.txt",
        "uv run pytest tests/unit && rm -rf services",
        "echo 'x' >> services/billets/src/billets/domaine/places.py",
        "python -c \"open('services/x.py', 'w')\"",
        "git checkout -- tests",
    ],
)
def test_le_shell_d_un_ecrivain_est_limite_a_sa_liste(commande: str) -> None:
    permises = ["uv run pytest", "make test-unit", "git status", "git diff"]

    assert limiter_commandes.decision(commande, permises) is not None


# Liste d'essai : avec make et docker compose, un refus prouve le filtrage de leurs arguments.
PERMISES_ESSAI = ["uv run pytest", "git diff", "make test-unit", "docker compose"]


def test_la_fusion_des_sorties_reste_permise() -> None:
    assert limiter_commandes.decision("uv run pytest tests/unit -q 2>&1", ["uv run pytest"]) is None


@pytest.mark.parametrize(
    "commande",
    [
        "uv run pytest tests/unit -q 2>&1 | tail -5",
        "cat services/echo/README.md",
        "head -40 docs/test-plans/BIL-F25.md | grep CA1",
        "git -C services/echo diff --stat",
        "cd services/echo && uv run pytest tests/unit -q",
        # Guillemets : leur contenu ne découpe ni ne redirige rien.
        "grep -n 'a;b' services/echo/README.md",
        'grep -E "lister|compter" services/echo/src/echo/infra/depot.py',
        "uv run pytest -k 'liste and (vide or page)' -q",
        "uv run pytest tests/unit -q -p no:cacheprovider",
        "make test-unit",
        "docker compose ps",
        "docker compose --profile observabilite up -d --wait",
        "docker compose -f compose.yaml logs echo-1",
    ],
)
def test_lire_sans_ecrire_est_permis_a_tous_les_agents(commande: str) -> None:
    assert limiter_commandes.decision(commande, PERMISES_ESSAI) is None  # BIL-F25


@pytest.mark.parametrize(
    "commande",
    [
        "uv run pytest $(rm -rf services)",
        "cat `rm -rf services`",
        "git -C services checkout -- tests",
        "sed -i 's/assert/# assert/' tests/unit/test_auth.py",
        "find . -name '*.py' -delete",
        "uv run pytest -q | tee rapport.txt",
        "cd services && rm -rf echo",
        # Failles relevées par la deuxième review de BIL-F25.
        "cat README.md & rm -rf services",
        "cat README.md &> tests/unit/test_x.py",
        "sort -o tests/unit/test_x.py README.md",
        "uniq README.md tests/unit/test_x.py",
        "git diff --output=tests/unit/test_x.py",
        'git diff "--output"=tests/unit/test_x.py',
        "uv run pytest --junitxml=tests/unit/test_x.py",
        "cat <(rm -rf services)",
        "(rm -rf services)",
        "cat 'README.md",
        'cat "$(rm -rf services)"',
        # Troisième review : guillemets lus autrement que par le shell.
        "cat \\' ; rm -rf services ; cat \\'",
        'cat \\" ; rm -rf services ; cat \\"',
        "cat $'\\'' ; rm -rf services ; cat $'\\''",
        "cat \u201c ; rm -rf services ; cat \u201d",
        "cat README.md\rrm -rf services",
        "git diff \\--output=tests/unit/test_x.py",
        "git diff \u2014output=tests/unit/test_x.py",
        # Arguments qui font écrire une commande permise.
        "make test-unit PYTEST=rm",
        "make -f /tmp/Makefile test-unit",
        "docker compose cp fichier echo-1:/app/tests/x.py",
        "docker compose run --rm echo sh",
        "docker compose exec echo-1 sh",
        "uv run pytest -c /tmp/pytest.ini",
        "uv run pytest -o addopts=-x",
        "uv run pytest --rootdir=/tmp",
        "uv run pytest -p greffon_maison",
        "uv run pytest -pgreffon_maison",
        # Quatrième review.
        "uv run pytest --debug=tests/unit/test_x.py",
        "docker compose cp fichier echo-1:/app/x.py",
        "docker compose --profile observabilite run echo sh",
        "docker compose create",
        "docker compose",
    ],
)
def test_la_lecture_ne_cache_aucune_ecriture(commande: str) -> None:
    assert limiter_commandes.decision(commande, PERMISES_ESSAI) is not None


# --- Implementer et reviewer (BIL-F22) -------------------------------------------------------


def test_implementer_et_reviewer_ont_leurs_outils() -> None:
    assert _entete("implementer")["tools"] == "Read, Grep, Glob, Write, Edit, Bash"
    assert _entete("reviewer")["tools"] == "Read, Grep, Glob, Write, Bash"
    assert _motifs_du_hook("reviewer") == ["docs/reviews/*.md"]


@pytest.mark.parametrize(
    ("chemin", "permis"),
    [
        ("services/billets/src/billets/domaine/places.py", True),
        ("services/billets/alembic/versions/0001_creer_places.py", True),
        ("services/billets/pyproject.toml", True),
        ("libs/commun/http.py", True),
        ("infra/verificateur/src/verificateur/principal.py", True),
        ("frontend/src/composants/CompteurPlaces.tsx", True),
        ("pyproject.toml", True),
        # Configuration du front (BIL-F26) et documentation de déploiement.
        ("frontend/vite.config.ts", True),
        ("frontend/playwright.config.ts", True),
        ("frontend/tsconfig.json", True),
        ("frontend/index.html", True),
        ("frontend/Dockerfile", True),
        ("frontend/nginx.conf", True),
        (".env.example", True),
        ("README.md", True),
        ("frontend/CLAUDE.md", False),
        # Tests et contrats : jamais, même dans un dossier autorisé (CA1).
        ("services/billets/tests/unit/test_places.py", False),
        ("services/billets/tests/integration/test_verrou.py", False),
        ("tests/unit/test_auth.py", False),
        ("libs/commun/tests/test_http.py", False),
        ("infra/verificateur/tests/unit/test_verificateur.py", False),
        ("frontend/src/composants/CompteurPlaces.test.tsx", False),
        ("frontend/e2e/achat.spec.ts", False),
        ("services/billets/openapi.yaml", False),
        ("docs/test-plans/BIL-006.md", False),
        (".claude/agents/implementer.md", False),
    ],
)
def test_implementer_n_ecrit_jamais_un_test_ni_un_contrat(chemin: str, permis: bool) -> None:
    assert limiter_ecriture.autorise(chemin, _motifs_du_hook("implementer")) is permis


@pytest.mark.parametrize(
    ("commande", "permis"),
    [
        ("git diff main...HEAD", True),
        ("git log --oneline -5", True),
        ("uv run pytest", False),
        ("git checkout -- services", False),
        ("git commit -m 'correction'", False),
    ],
)
def test_reviewer_ne_lance_que_git_en_lecture(commande: str, permis: bool) -> None:
    permises = _arguments_du_hook("reviewer", "limiter_commandes.py", "Bash|PowerShell")

    assert (limiter_commandes.decision(commande, permises) is None) is permis


def test_le_reviewer_controle_la_configuration_de_vitest() -> None:
    """BIL-F26 : vite.config.ts reste modifiable par implementer (build), donc sa partie tests est
    vérifiée en review."""
    consignes = (AGENTS / "reviewer.md").read_text(encoding="utf-8")

    assert "bloc `test` de `frontend/vite.config.ts`" in consignes


def test_une_exclusion_l_emporte_sur_une_autorisation() -> None:
    motifs = ["libs/**", "!**/tests/**"]

    assert limiter_ecriture.autorise("libs/commun/auth.py", motifs)
    assert not limiter_ecriture.autorise("libs/commun/tests/test_auth.py", motifs)


@pytest.mark.parametrize("fichier", sorted(AGENTS.glob("*.md")), ids=lambda f: f.stem)
def test_chaque_agent_a_un_en_tete_lisible(fichier: Path) -> None:
    """Un en-tête YAML invalide (« : » non protégé dans la description) rendrait l'agent
    illisible pour Claude Code."""
    entete = _entete(fichier.stem)

    assert entete["name"] == fichier.stem
    assert isinstance(entete["description"], str) and entete["description"]
    assert entete["tools"]
