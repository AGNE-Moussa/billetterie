"""Stop : tests rapides de ce qui a changé, avant que l'agent rende la main.

Fichiers modifiés depuis le dernier commit (suivis ou nouveaux) : du Python lance les tests
unitaires (pytest), du code du front lance Vitest. Jamais Testcontainers ni Playwright, trop
lents pour chaque tour. En cas d'échec, l'agent doit corriger ; s'il s'arrête de nouveau avec
des tests rouges (stop_hook_active), il est laissé finir, avec l'échec signalé.

Aux étapes « tests » et « implementation » (marqueur `.pipeline/etape`), des tests rouges sont
attendus : le hook ne les lance pas. Pendant l'implémentation, l'agent `implementer` travaille en
fond et la session principale rend la main à chaque tour ; elle vérifie le vert elle-même
(`/ticket`, étape 6) une fois l'agent terminé.
"""

import json
import subprocess
import sys
from pathlib import Path

from _commun import bloquer, etape_courante, lire_entree, racine_projet

EXTENSIONS_FRONT = (".ts", ".tsx", ".js", ".jsx", ".css")
# Étapes où des tests rouges sont attendus : rien à faire corriger.
ETAPES_ROUGES_ATTENDUS = {"tests", "implementation"}
LIGNES_SORTIE = 40


def fichiers_modifies(racine: Path) -> list[str]:
    commandes = [
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]
    fichiers: list[str] = []
    for commande in commandes:
        sortie = subprocess.run(
            commande, cwd=racine, capture_output=True, text=True, encoding="utf-8", timeout=30
        )
        fichiers += [ligne for ligne in sortie.stdout.splitlines() if ligne]
    return fichiers


def a_lancer(fichiers: list[str]) -> list[str]:
    """Suites à lancer : « pytest » si du Python a changé, « vitest » si le front a changé."""
    suites = []
    if any(f.endswith(".py") for f in fichiers):
        suites.append("pytest")
    if any(f.startswith("frontend/") and f.endswith(EXTENSIONS_FRONT) for f in fichiers):
        suites.append("vitest")
    return suites


def commande(suite: str, racine: Path) -> list[str] | None:
    if suite == "pytest":
        dossiers = [racine / "tests" / "unit", *racine.glob("services/*/tests/unit")]
        dossiers += racine.glob("infra/*/tests/unit")
        chemins = [d.relative_to(racine).as_posix() for d in dossiers if d.is_dir()]
        return ["uv", "run", "--no-sync", "pytest", "-q", "-x", *chemins]
    if (racine / "frontend" / "package.json").exists():
        # --if-present : sans script test (avant BIL-F26), rien n'est lancé.
        return ["npm", "--prefix", "frontend", "run", "--if-present", "test", "--", "--run"]
    return None


def main() -> None:
    entree = lire_entree()
    racine = racine_projet()
    if etape_courante(racine) in ETAPES_ROUGES_ATTENDUS:
        return
    echecs = []
    for suite in a_lancer(fichiers_modifies(racine)):
        cmd = commande(suite, racine)
        if cmd is None:
            continue
        resultat = subprocess.run(
            cmd,
            cwd=racine,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=540,
            shell=sys.platform == "win32" and cmd[0] == "npm",  # npm est un .cmd sous Windows
        )
        if resultat.returncode != 0:
            fin = (resultat.stdout + resultat.stderr).strip().splitlines()[-LIGNES_SORTIE:]
            echecs.append(f"{suite} en échec :\n" + "\n".join(fin))
    if not echecs:
        return
    rapport = "Tests rapides en échec, à corriger avant de rendre la main.\n\n" + "\n\n".join(
        echecs
    )
    if entree.get("stop_hook_active"):
        # Déjà relancé une fois par ce hook : on laisse finir, sans boucle, en le signalant.
        print(json.dumps({"systemMessage": rapport}))
        return
    bloquer(rapport)


if __name__ == "__main__":
    main()
