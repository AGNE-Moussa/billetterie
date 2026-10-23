"""PreToolUse d'un agent : il n'écrit que dans les chemins qu'on lui autorise.

Déclaré dans l'en-tête de l'agent (hooks de .claude/agents/*.md), actif seulement pendant qu'il
travaille. Les motifs sont relatifs au projet, un segment par niveau de dossier :

    limiter_ecriture.py "docs/test-plans/*.md"        # test-planner
    limiter_ecriture.py "services/*/openapi.yaml"     # contract-writer
    limiter_ecriture.py "libs/**" "!**/tests/**"      # « ! » : exclusion, prioritaire
"""

import sys
from fnmatch import fnmatchcase

from _commun import bloquer, chemin_relatif, lire_entree, racine_projet


def _correspond(segments: list[str], attendus: list[str]) -> bool:
    if not attendus:
        return not segments
    if attendus[0] == "**":
        # « ** » : zéro, un ou plusieurs dossiers.
        return any(_correspond(segments[i:], attendus[1:]) for i in range(len(segments) + 1))
    return (
        bool(segments)
        and fnmatchcase(segments[0], attendus[0])
        and _correspond(segments[1:], attendus[1:])
    )


def autorise(chemin_rel: str | None, motifs: list[str]) -> bool:
    """Vrai si le chemin correspond à un motif, segment par segment.

    « * » ne franchit pas « / » : `services/*/openapi.yaml` n'autorise pas un sous-dossier.
    « ** » couvre n'importe quelle profondeur : `tests/unit/**`.
    « ! » en tête exclut : `!**/tests/**` l'emporte sur toute autorisation.
    """
    if chemin_rel is None:
        return False  # hors du projet : jamais pour un agent du pipeline
    segments = chemin_rel.split("/")
    exclusions = [m[1:] for m in motifs if m.startswith("!")]
    if any(_correspond(segments, motif.split("/")) for motif in exclusions):
        return False
    inclusions = [m for m in motifs if not m.startswith("!")]
    return any(_correspond(segments, motif.split("/")) for motif in inclusions)


def main() -> None:
    motifs = sys.argv[1:]
    entree = lire_entree()
    chemin = entree.get("tool_input", {}).get("file_path") or entree.get("tool_input", {}).get(
        "notebook_path"
    )
    if not chemin:
        return
    chemin_rel = chemin_relatif(chemin, racine_projet())
    if not autorise(chemin_rel, motifs):
        agent = entree.get("agent_type", "cet agent")
        bloquer(
            f"Écriture refusée : {agent} n'écrit que dans {', '.join(motifs)} "
            f"(demandé : {chemin_rel or chemin})."
        )


if __name__ == "__main__":
    main()
