"""PreToolUse d'un agent sur Bash et PowerShell : seules les commandes de sa liste blanche passent.

Déclaré dans l'en-tête des agents qui lancent des commandes (.claude/agents/*.md). Une liste
blanche plutôt qu'une liste noire : le shell peut écrire n'importe où, on n'autorise donc que les
commandes utiles à l'agent.

    limiter_commandes.py "uv run pytest" "make test-unit" "git diff"

C'est un filtre au mieux, pas un analyseur de shell : il ne lit pas une commande exactement comme
bash ou PowerShell. Il est donc écrit pour refuser dans le doute, et il n'est qu'une défense parmi
d'autres (proteger_fichiers et git_sur pour les tests et le contrat, la review qui vérifie que
les tests n'ont pas changé, la CI). Pour que les guillemets se lisent de la même façon dans les
deux shells, les caractères qui échappent, développent ou redirigent sont refusés partout
(INTERDITS), ainsi que tout caractère non ASCII (PowerShell lit « “ » comme un guillemet et « — »
comme un tiret).

Les commandes de lecture seule (LECTURE_SEULE) sont permises à tous les agents, seules ou dans un
pipe : `uv run pytest -q | tail -5`. `cd <dossier>` et `git -C <dossier>` aussi, puisqu'ils ne
changent que le dossier où la commande suivante s'exécute.

Limite connue : une commande permise garde certains arguments qui écrivent (scripts npm, options
de Vitest et de Playwright, comme ses rapports et traces). Ceux de make, docker compose (liste
blanche de sous-commandes, COMPOSE) et pytest sont filtrés (_argument_refuse).
"""

import re
import sys

from _commun import bloquer, lire_entree

# « & » seul lance en fond et enchaîne une autre commande : c'est aussi un séparateur.
SEPARATEURS = re.compile(r"&&|\|\||;|\||&|\n")
# Échappement (\), variables et substitutions ($, `), blocs ({ }), redirections (< >), retour
# chariot seul, et tout caractère non ASCII.
INTERDITS = re.compile(r"[\\$`{}<>\r]|[^\x00-\x7f]")
# Sans échappement possible, un texte entre guillemets se lit pareil dans les deux shells.
GUILLEMETS = re.compile(r"'[^']*'|\"[^\"]*\"")
# Options qui écrivent un fichier choisi par l'appelant.
OPTIONS_ECRITURE = re.compile(
    r"(^|\s)(--output|--junit-?xml|--log-file|--report-log|--html|--cov-report|--basetemp|--debug)"
    r"\b"
)
# Lisent sans rien écrire. Ni sed (-i), ni find (-delete, -exec), ni tee, sort (-o) ou uniq
# (fichier de sortie) : ils savent écrire.
LECTURE_SEULE = ["cat", "head", "tail", "wc", "ls", "grep", "cut"]
# Sous-commandes qui gèrent les conteneurs sans copier de fichier ni lancer de commande dedans
# (ni cp, ni run, ni exec).
COMPOSE = {"up", "down", "ps", "logs", "build", "config", "pull", "stop", "start"}
OPTIONS_COMPOSE_A_VALEUR = {"-f", "--file", "-p", "--project-name", "--profile", "--env-file"}


def _hors_guillemets(commande: str) -> str | None:
    """La commande où chaque texte entre guillemets devient « _ » ; None si l'un n'est pas fermé."""
    nue = GUILLEMETS.sub("_", commande)
    return None if "'" in nue or '"' in nue else nue


def _sans_dossier(mots: list[str]) -> list[str]:
    """« git -C <dossier> diff » se lit « git diff »."""
    if mots[:2] == ["git", "-C"]:
        return ["git", *mots[3:]]
    return mots


def _sous_commande_compose(mots: list[str]) -> str | None:
    """La sous-commande de « docker compose », après ses options globales et leur valeur."""
    i = 0
    while i < len(mots) and mots[i].startswith("-"):
        i += 2 if mots[i] in OPTIONS_COMPOSE_A_VALEUR else 1
    return mots[i] if i < len(mots) else None


def _argument_refuse(mots: list[str]) -> str | None:
    """Argument d'une commande permise qui la ferait écrire ailleurs, ou None."""
    if mots[0] == "make" and any(not re.fullmatch(r"[a-z][a-z-]*", mot) for mot in mots[1:]):
        return "make n'accepte que des cibles (ni variable ni option)"
    if mots[:2] == ["docker", "compose"] and _sous_commande_compose(mots[2:]) not in COMPOSE:
        return f"docker compose n'accepte que {', '.join(sorted(COMPOSE))}"
    if "pytest" in mots[:3]:
        for i, mot in enumerate(mots):
            if mot in {"-c", "-o", "--rootdir", "--override-ini", "--config-file"} or (
                mot.startswith(("--rootdir=", "--override-ini=", "--config-file="))
            ):
                return f"l'option pytest {mot} change la configuration"
            suivant = mots[i + 1] if i + 1 < len(mots) else ""
            greffon = suivant if mot == "-p" else mot[2:] if mot.startswith("-p") else None
            if greffon is not None and not greffon.startswith("no:"):
                return "pytest -p ne sert qu'à désactiver un greffon (-p no:...)"
    return None


def decision(commande: str, permises: list[str]) -> str | None:
    """Motif du refus, ou None si chaque morceau de la commande est permis."""
    sans_fusion = commande.replace("2>&1", "")
    if INTERDITS.search(sans_fusion):
        return (
            "Commande refusée : caractère interdit (\\ $ ` { } < >, retour chariot ou non ASCII). "
            "Pour lire un fichier, utiliser l'outil Read."
        )
    nue = _hors_guillemets(sans_fusion)
    if nue is None:
        return "Commande refusée : guillemet non fermé."
    if "(" in nue or ")" in nue:
        return "Commande refusée : pas de sous-shell ni de groupe entre parenthèses."
    # Le shell retire les guillemets : « "--output"=f » se lit « --output=f ».
    if OPTIONS_ECRITURE.search(re.sub(r"['\"]", "", sans_fusion)):
        return "Commande refusée : option qui écrit un fichier (--output, --junitxml…)."
    toutes = [*permises, *LECTURE_SEULE]
    for morceau in SEPARATEURS.split(nue):
        mots = _sans_dossier(morceau.split())
        if not mots or (mots[0] == "cd" and len(mots) <= 2):
            continue
        if not any(mots[: len(p.split())] == p.split() for p in toutes):
            return (
                f"Commande refusée : « {morceau.strip()} » n'est pas dans la liste de cet agent "
                f"({' ; '.join(permises)}) ni dans les commandes de lecture "
                f"({', '.join(LECTURE_SEULE)})."
            )
        motif = _argument_refuse(mots)
        if motif:
            return f"Commande refusée : {motif} (« {morceau.strip()} »)."
    return None


def main() -> None:
    commande = lire_entree().get("tool_input", {}).get("command", "")
    motif = decision(commande, sys.argv[1:])
    if motif:
        bloquer(motif)


if __name__ == "__main__":
    main()
