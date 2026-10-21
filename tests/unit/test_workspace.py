"""Le workspace uv liste explicitement ses membres : il doit rester cohérent avec le dépôt."""

import tomllib
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]


def _membres() -> list[str]:
    configuration = tomllib.loads((RACINE / "pyproject.toml").read_text(encoding="utf-8"))
    membres: list[str] = configuration["tool"]["uv"]["workspace"]["members"]
    return membres


def test_chaque_membre_declare_a_son_pyproject() -> None:
    for membre in _membres():
        assert (RACINE / membre / "pyproject.toml").is_file(), membre


def test_chaque_service_avec_un_pyproject_est_un_membre() -> None:
    """Un service dont le code existe doit être déclaré ; un dossier qui n'a encore que son
    contrat (contrat d'abord) ne l'est pas."""
    projets = [p.parent for p in RACINE.glob("services/*/pyproject.toml")]
    projets += [p.parent for p in RACINE.glob("infra/*/pyproject.toml")]

    for projet in projets:
        assert projet.relative_to(RACINE).as_posix() in _membres(), projet
