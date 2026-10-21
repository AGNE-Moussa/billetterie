"""PostToolUse sur Edit et Write : formatage, puis erreurs renvoyées à l'agent.

- `.py` du projet : `ruff format`, puis `ruff check` ;
- `.ts`, `.tsx`, `.js` de `frontend/` : `prettier --write`, puis `eslint`
  (outils de `frontend/node_modules`, installés par `npm install`).
"""

import shutil
import subprocess
from pathlib import Path

from _commun import bloquer, chemin_relatif, lire_entree, racine_projet

EXTENSIONS_FRONT = (".ts", ".tsx", ".js")


def commandes(chemin_rel: str, racine: Path) -> list[tuple[list[str], Path]]:
    """Commandes à lancer pour ce fichier, chacune avec son dossier de travail."""
    if chemin_rel.endswith(".py"):
        ruff = ["uv", "run", "--no-sync", "ruff"]
        return [(ruff + ["format", chemin_rel], racine), (ruff + ["check", chemin_rel], racine)]
    if chemin_rel.startswith("frontend/") and chemin_rel.endswith(EXTENSIONS_FRONT):
        front = racine / "frontend"
        outils = front / "node_modules" / ".bin"
        prettier = shutil.which("prettier", path=str(outils))
        eslint = shutil.which("eslint", path=str(outils))
        if not (prettier and eslint):
            return []  # outillage pas installé (npm install dans frontend/)
        fichier = chemin_rel.removeprefix("frontend/")
        return [([prettier, "--write", fichier], front), ([eslint, fichier], front)]
    return []


def main() -> None:
    chemin = lire_entree().get("tool_input", {}).get("file_path")
    if not chemin:
        return
    racine = racine_projet()
    chemin_rel = chemin_relatif(chemin, racine)
    if chemin_rel is None:
        return
    for commande, dossier in commandes(chemin_rel, racine):
        resultat = subprocess.run(
            commande, cwd=dossier, capture_output=True, text=True, encoding="utf-8", timeout=120
        )
        if resultat.returncode != 0:
            sortie = (resultat.stdout + resultat.stderr).strip()
            bloquer(f"{Path(commande[0]).stem} {chemin_rel} a signalé des erreurs :\n{sortie}")


if __name__ == "__main__":
    main()
