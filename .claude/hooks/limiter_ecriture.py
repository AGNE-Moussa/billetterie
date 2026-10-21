"""PreToolUse d'un agent : il n'écrit que dans les chemins qu'on lui autorise.

Déclaré dans l'en-tête de l'agent (hooks de .claude/agents/*.md), actif seulement pendant qu'il
travaille. Les motifs sont relatifs au projet, un segment par niveau de dossier :

    limiter_ecriture.py "docs/test-plans/*.md"        # test-planner
    limiter_ecriture.py "services/*/openapi.yaml"     # contract-writer
"""

import sys
from fnmatch import fnmatchcase

from _commun import bloquer, chemin_relatif, lire_entree, racine_projet


def autorise(chemin_rel: str | None, motifs: list[str]) -> bool:
    """Vrai si le chemin correspond à un motif, segment par segment.

    « * » ne franchit pas « / » : `services/*/openapi.yaml` n'autorise pas un sous-dossier.
    """
    if chemin_rel is None:
        return False  # hors du projet : jamais pour un agent du pipeline
    segments = chemin_rel.split("/")
    for motif in motifs:
        attendus = motif.split("/")
        if len(attendus) == len(segments) and all(map(fnmatchcase, segments, attendus)):
            return True
    return False


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
