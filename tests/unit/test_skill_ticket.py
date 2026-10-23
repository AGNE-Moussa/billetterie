"""Skill /ticket (BIL-F23) : en-tête lisible et règles qui ne doivent pas disparaître."""

from pathlib import Path

import yaml

SKILL = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "ticket" / "SKILL.md"
MCP = Path(__file__).resolve().parents[2] / ".mcp.json"


def _texte() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_l_en_tete_est_lisible() -> None:
    entete = yaml.safe_load(_texte().split("---\n", 2)[1])

    assert entete["name"] == "ticket"
    assert entete["description"]


def test_le_skill_garde_ses_regles_absolues() -> None:
    texte = _texte()

    # Notion seule source, arrêt si indisponible ; jamais TO TEST ni DONE ; validations humaines.
    assert "ne reconstitue jamais un ticket de mémoire" in texte
    assert "**Jamais** `TO TEST` ni" in texte
    assert texte.count("arrête-toi") >= 4  # bloquants, contrat, validation 1, validation 2
    assert "Validation 1 : arrête-toi" in texte
    assert "Validation 2 : arrête-toi" in texte
    assert "**ne l'écrase pas**" in texte  # docs/tickets/<ID>.md existant conservé


def test_le_serveur_mcp_du_projet_ne_contient_aucun_jeton() -> None:
    texte = MCP.read_text(encoding="utf-8").lower()

    assert '"url": "https://mcp.notion.com/mcp"' in texte
    for mot in ("token", "authorization", "bearer", "secret", "key"):
        assert mot not in texte
