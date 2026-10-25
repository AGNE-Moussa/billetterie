"""Fixtures des tests unitaires communs."""

import os
import shutil
from pathlib import Path

import pytest


@pytest.fixture
def shell_posix() -> str:
    """Chemin d'un `sh` POSIX pour exécuter un script livré, sans Docker.

    Sous Windows, le `sh` de Git for Windows (jamais le `bash.exe` de WSL, qui ne voit pas les
    chemins Windows).
    """
    git = shutil.which("git")
    candidats = [shutil.which("sh")]
    if git:
        racine_git = Path(git).resolve().parents[1]
        candidats += [
            str(racine_git / "usr" / "bin" / "sh.exe"),
            str(racine_git / "bin" / "sh.exe"),
        ]
    for candidat in candidats:
        if candidat and Path(candidat).is_file():
            return candidat
    pytest.skip("aucun sh POSIX disponible pour exécuter le script")


@pytest.fixture
def path_posix(shell_posix: str) -> str:
    """PATH du sous-processus : outils POSIX du même environnement que `shell_posix` en tête.

    Lancé depuis PowerShell, le PATH ne contient pas Git\\usr\\bin : sans ce préfixe, `sed` ou
    `cat` seraient introuvables (code 127) et le script planterait au lieu de s'exécuter.
    """
    dossier = Path(shell_posix).resolve().parent
    dossiers = [dossier]
    # sh de Git for Windows : <Git>\usr\bin\sh.exe ou <Git>\bin\sh.exe ; outils dans usr\bin.
    outils_git = dossier.parent / "usr" / "bin"
    if outils_git.is_dir() and outils_git != dossier:
        dossiers.append(outils_git)
    return os.pathsep.join([*map(str, dossiers), os.environ.get("PATH", "")])
