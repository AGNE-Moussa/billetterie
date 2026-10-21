"""Outils partagés par les hooks de Claude Code (bibliothèque standard seulement).

Un hook reçoit sur stdin le JSON de l'événement (outil appelé, paramètres). Code de sortie 2 :
l'action est bloquée (PreToolUse) ou l'agent doit réagir (PostToolUse, Stop), et le message
écrit sur stderr lui est renvoyé. Code 0 : rien à signaler.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

CODE_BLOCAGE = 2

# Messages en UTF-8, même sous Windows où une sortie redirigée serait en cp1252 : sans cela,
# les accents des messages renvoyés à l'agent deviennent illisibles.
for _flux in (sys.stdout, sys.stderr):
    if hasattr(_flux, "reconfigure"):
        _flux.reconfigure(encoding="utf-8")


def lire_entree() -> dict[str, Any]:
    texte = sys.stdin.read()
    entree: dict[str, Any] = json.loads(texte) if texte.strip() else {}
    return entree


def bloquer(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    sys.exit(CODE_BLOCAGE)


def racine_projet() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()).resolve()


def branche_courante(racine: Path) -> str | None:
    try:
        sortie = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=racine,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return sortie.stdout.strip() or None


def etape_courante(racine: Path) -> str | None:
    """Valeur du marqueur `.claude/etape` posé par /ticket (docs/workflow.md) ; None si absent."""
    marqueur = racine / ".claude" / "etape"
    try:
        valeur = marqueur.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return valeur or None


def chemin_relatif(chemin: str, racine: Path) -> str | None:
    """Chemin relatif au projet, avec des « / » ; None si le fichier est hors du projet."""
    try:
        return Path(chemin).resolve().relative_to(racine).as_posix()
    except ValueError:
        return None
