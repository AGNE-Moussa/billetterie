"""PreToolUse sur Bash et PowerShell : commandes interdites, sans exception.

- `git push --force` (et `-f`, `--force-with-lease`, refspec en `+`) ;
- `git push` vers `main` et `git merge` sur `main` : `main` change seulement par une PR ;
- `gh pr merge` : le merge est humain ;
- écriture dans `.env` par redirection ou commande PowerShell (Edit et Write sont couverts par
  proteger_fichiers.py ; une écriture par le shell n'y passe pas) ;
- écriture par le shell dans les tests verrouillés ou dans un contrat hors de l'étape `contrat`
  (même marqueur que proteger_fichiers.py).

La détection des écritures par le shell est une heuristique (redirections, tee, Set-Content,
Out-File, cp, mv, sed -i) : un programme qui écrit lui-même un fichier n'est pas vu.
"""

import re
import shlex

from _commun import bloquer, branche_courante, etape_courante, lire_entree, racine_projet
from proteger_fichiers import (
    CONFIG_TESTS,
    ETAPES_CONFIG_TESTS_VERROUILLEE,
    ETAPES_TESTS_VERROUILLES,
    TESTS,
)

SEPARATEURS = re.compile(r"&&|\|\||;|\||\n")
OPTIONS_FORCE = {"-f", "--force", "--force-with-lease", "--force-if-includes"}
ECRITURE_ENV = re.compile(
    # .env et ses variantes (.env.local, .env.production), mais pas .env.example.
    r"(>>?|\b(set-content|add-content|out-file|tee)\b)[^;&|\n]*?(^|[\s'\"/\\])"
    r"\.env(?!\.example)(\.\w+)?(?![\w.])",
    re.IGNORECASE,
)


def _mots(segment: str) -> list[str]:
    # Mode non POSIX : les « \ » des chemins Windows (PowerShell) sont conservés.
    try:
        mots = shlex.split(segment, posix=False)
    except ValueError:
        mots = segment.split()
    return [mot.strip("'\"") for mot in mots]


def _sous_commande(mots: list[str], programme: str) -> list[str] | None:
    """Arguments qui suivent `programme` (git, gh), ou None s'il n'est pas appelé."""
    for i, mot in enumerate(mots):
        if mot.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower() in (programme, f"{programme}.exe"):
            return mots[i + 1 :]
    return None


REDIRECTION = re.compile(r">>?\s*['\"]?([^\s'\";&|]+)")
ECRITURE_PREMIER_ARGUMENT = {"tee", "set-content", "add-content", "out-file", "new-item"}
ECRITURE_DERNIER_ARGUMENT = {"cp", "mv", "copy-item", "move-item", "copy", "move"}


def _cibles_ecrites(segment: str, mots: list[str]) -> list[str]:
    """Fichiers qu'un segment de commande écrit, d'après sa forme."""
    cibles = REDIRECTION.findall(segment)
    nom = mots[0].lower() if mots else ""
    arguments = [m for m in mots[1:] if not m.startswith("-")]
    if nom in ECRITURE_PREMIER_ARGUMENT and arguments:
        cibles.append(arguments[0])
    if nom in ECRITURE_DERNIER_ARGUMENT and arguments:
        cibles.append(arguments[-1])
    if nom == "sed" and "-i" in mots:
        cibles += arguments
    return [c.replace("\\", "/").removeprefix("./") for c in cibles]


def _ecriture_verrouillee(cible: str, etape: str | None) -> str | None:
    if etape in ETAPES_TESTS_VERROUILLES and TESTS.search(cible):
        return (
            f"Commande refusée : les tests sont verrouillés à l'étape « {etape} » ({cible}). "
            "L'implémentation fait passer les tests, elle ne les modifie pas."
        )
    if etape in ETAPES_CONFIG_TESTS_VERROUILLEE and CONFIG_TESTS.search(cible):
        return f"Commande refusée : la configuration des tests {cible} est verrouillée."
    if etape is not None and etape != "contrat" and cible.endswith("openapi.yaml"):
        return f"Commande refusée : le contrat {cible} ne se modifie qu'à l'étape « contrat »."
    return None


def decision(commande: str, branche: str | None, etape: str | None = None) -> str | None:
    """Motif du refus, ou None si la commande est permise."""
    if ECRITURE_ENV.search(commande):
        return "Commande refusée : .env ne s'écrit pas par le shell, seulement à la main."
    sur_main = branche == "main"
    for segment in SEPARATEURS.split(commande):
        mots = _mots(segment.strip())
        for cible in _cibles_ecrites(segment, mots):
            if motif := _ecriture_verrouillee(cible, etape):
                return motif
        git = _sous_commande(mots, "git")
        gh = _sous_commande(mots, "gh")
        if gh and gh[:2] == ["pr", "merge"]:
            return "Commande refusée : gh pr merge. Le merge est humain (docs/workflow.md)."
        if not git:
            continue
        if git[0] in ("switch", "checkout") and "main" in git[1:]:
            sur_main = True
        if git[0] == "push":
            options = set(git[1:])
            if options & OPTIONS_FORCE or any(m.startswith("+") for m in git[1:]):
                return "Commande refusée : git push forcé. L'historique partagé ne se réécrit pas."
            if any(m == "main" or m.endswith(":main") for m in git[1:]):
                return "Commande refusée : push vers main. main change seulement par une PR."
        if git[0] == "merge" and sur_main:
            return "Commande refusée : git merge sur main. main change seulement par une PR."
    return None


def main() -> None:
    commande = lire_entree().get("tool_input", {}).get("command", "")
    racine = racine_projet()
    motif = decision(commande, branche_courante(racine), etape_courante(racine))
    if motif:
        bloquer(motif)


if __name__ == "__main__":
    main()
