"""Rules de .claude/rules/ : courtes, et chargées seulement pour les chemins prévus (BIL-F18)."""

from pathlib import Path

import pytest
import yaml

DOSSIER = Path(__file__).resolve().parents[2] / ".claude" / "rules"
LIGNES_MAX = 30

# Rule -> motifs `paths` attendus ; None : rule chargée tout le temps (pas d'en-tête paths).
ATTENDUES: dict[str, list[str] | None] = {
    "python.md": ["services/**/*.py", "libs/**/*.py", "infra/**/*.py"],
    "tests.md": ["**/tests/**", "frontend/**/*.test.tsx", "frontend/e2e/**"],
    "contrats-api.md": ["**/openapi.yaml", "docs/contrats/*.yaml", "services/*/src/**/api/**"],
    "evenements.md": [
        "services/*/src/**/infra/**",
        "services/*/src/**/evenements/**",
        "libs/commun/evenements.py",
        "libs/commun/outbox.py",
        "libs/commun/consommateurs.py",
    ],
    "migrations.md": ["**/alembic/**"],
    "securite.md": None,
    "git.md": None,
    "frontend.md": ["frontend/**"],
    "places-concurrence.md": ["services/billets/**", "services/commandes/**"],
    "billets-qr.md": ["services/billets/**"],
}


def _paths(rule: Path) -> list[str] | None:
    texte = rule.read_text(encoding="utf-8")
    if not texte.startswith("---\n"):
        return None
    entete = yaml.safe_load(texte.split("---\n", 2)[1])
    paths: list[str] = entete["paths"]
    return paths


def test_les_rules_prevues_existent_et_aucune_autre() -> None:
    assert sorted(rule.name for rule in DOSSIER.glob("*.md")) == sorted(ATTENDUES)


@pytest.mark.parametrize("nom", sorted(ATTENDUES))
def test_une_rule_ne_depasse_pas_30_lignes(nom: str) -> None:
    lignes = (DOSSIER / nom).read_text(encoding="utf-8").splitlines()

    assert len(lignes) <= LIGNES_MAX, f"{nom} : {len(lignes)} lignes"


@pytest.mark.parametrize(("nom", "paths"), sorted(ATTENDUES.items()))
def test_une_rule_n_est_chargee_que_pour_ses_chemins(nom: str, paths: list[str] | None) -> None:
    assert _paths(DOSSIER / nom) == paths
