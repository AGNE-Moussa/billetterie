"""PreToolUse sur Edit, Write et NotebookEdit : écritures interdites.

- `.env` et ses variantes (sauf `.env.example`) et les fichiers de secrets, où qu'ils soient ;
- tout fichier du projet quand la branche courante est `main` ;
- les tests pendant le squelette, l'implémentation, la review et la PR (marqueur `.claude/etape`) ;
- les contrats `openapi.yaml` hors de l'étape `contrat`, quand un marqueur est posé.
"""

import re
from pathlib import PurePosixPath

from _commun import (
    bloquer,
    branche_courante,
    chemin_relatif,
    etape_courante,
    lire_entree,
    racine_projet,
)

EXTENSIONS_SECRETS = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"}
NOMS_SECRETS = re.compile(r"^(id_rsa|id_ecdsa|id_ed25519|credentials|secrets?)(\..+)?$")
# « squelette » : implementer prépare le code vide avant les tests, il ne les écrit pas.
ETAPES_TESTS_VERROUILLES = {"squelette", "implementation", "review", "pr"}
TESTS = re.compile(r"(^|/)tests/|\.test\.tsx?$|^frontend/e2e/")


def decision(
    chemin_rel: str | None, nom: str, branche: str | None, etape: str | None
) -> str | None:
    """Motif du refus, ou None si l'écriture est permise."""
    if nom.startswith(".env") and nom != ".env.example":
        return (
            f"Écriture refusée : {nom} contient des secrets locaux, il ne se modifie qu'à la main."
        )
    if PurePosixPath(nom).suffix in EXTENSIONS_SECRETS or NOMS_SECRETS.match(nom):
        return f"Écriture refusée : {nom} ressemble à un fichier de secrets."
    if chemin_rel is None:
        return None  # hors du projet (mémoire de Claude, dossier temporaire)
    if branche == "main":
        return (
            "Écriture refusée : la branche courante est main, protégée. Créer d'abord la branche "
            "du ticket (propriété Branche dans Notion)."
        )
    if etape in ETAPES_TESTS_VERROUILLES and TESTS.search(chemin_rel):
        return (
            f"Écriture refusée : les tests sont verrouillés à l'étape « {etape} » "
            f"({chemin_rel}). L'implémentation fait passer les tests, elle ne les modifie pas."
        )
    if etape is not None and etape != "contrat" and nom == "openapi.yaml":
        return (
            f"Écriture refusée : le contrat {chemin_rel} ne se modifie qu'à l'étape « contrat » "
            f"(étape actuelle : « {etape} »)."
        )
    return None


def main() -> None:
    entree = lire_entree().get("tool_input", {})
    chemin = entree.get("file_path") or entree.get("notebook_path")
    if not chemin:
        return
    racine = racine_projet()
    motif = decision(
        chemin_relatif(chemin, racine),
        PurePosixPath(chemin.replace("\\", "/")).name,
        branche_courante(racine),
        etape_courante(racine),
    )
    if motif:
        bloquer(motif)


if __name__ == "__main__":
    main()
