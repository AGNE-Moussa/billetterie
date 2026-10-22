"""PreToolUse d'un agent sur Bash et PowerShell : seules les commandes de sa liste blanche passent.

Déclaré dans l'en-tête des agents qui lancent des tests (.claude/agents/*-test-writer.md). Une
liste blanche plutôt qu'une liste noire : le shell peut écrire n'importe où, on n'autorise donc
que les commandes utiles à l'agent, sans redirection vers un fichier.

    limiter_commandes.py "uv run pytest" "make test-unit" "git diff"
"""

import re
import sys

from _commun import bloquer, lire_entree

SEPARATEURS = re.compile(r"&&|\|\||;|\||\n")
# Redirection vers un fichier ; « 2>&1 » (fusion des sorties) reste permis.
REDIRECTION = re.compile(r"(?<![0-9&])>|[0-9]>(?!&)")


def decision(commande: str, permises: list[str]) -> str | None:
    """Motif du refus, ou None si chaque morceau de la commande est permis."""
    if REDIRECTION.search(commande.replace("2>&1", "")):
        return "Commande refusée : pas de redirection vers un fichier (>)."
    for morceau in SEPARATEURS.split(commande):
        mots = morceau.split()
        if not mots:
            continue
        if not any(mots[: len(p.split())] == p.split() for p in permises):
            return (
                f"Commande refusée : « {morceau.strip()} » n'est pas dans la liste de cet agent "
                f"({' ; '.join(permises)})."
            )
    return None


def main() -> None:
    commande = lire_entree().get("tool_input", {}).get("command", "")
    motif = decision(commande, sys.argv[1:])
    if motif:
        bloquer(motif)


if __name__ == "__main__":
    main()
