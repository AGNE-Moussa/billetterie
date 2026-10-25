"""Aucun secret en clair dans la composition de prod ni dans son modèle d'environnement (CA3)."""

import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

RACINE = Path(__file__).resolve().parents[2]
COMPOSE_PROD = RACINE / "compose.prod.yaml"
MODELE_PROD = RACINE / ".env.prod.example"
# Mots d'un nom de variable (séparés par `_`) qui la rendent sensible ; MDP : mot de passe.
MOTS_SENSIBLES = {"PASSWORD", "PASS", "SECRET", "TOKEN", "KEY", "MDP"}
SUFFIXES_SENSIBLES = ("DATABASE_URL", "DB_URL", "RABBITMQ_URL")
INTERPOLATION_OBLIGATOIRE = re.compile(r"\$\{[A-Z][A-Z0-9_]*:\?[^}]*\}")


def _est_sensible(nom: str) -> bool:
    return bool(MOTS_SENSIBLES & set(nom.split("_"))) or nom.endswith(SUFFIXES_SENSIBLES)


def _environnement(service: dict[str, Any]) -> dict[str, str]:
    brut = service.get("environment") or {}
    if isinstance(brut, list):
        return dict(str(ligne).partition("=")[::2] for ligne in brut)
    return {str(nom): "" if valeur is None else str(valeur) for nom, valeur in brut.items()}


def _ignore_par_git(chemin: str) -> bool:
    resultat = subprocess.run(
        ["git", "check-ignore", "-q", chemin], cwd=RACINE, check=False, capture_output=True
    )
    return resultat.returncode == 0


def test_les_variables_sensibles_de_prod_sont_toutes_interpolees() -> None:
    compose = yaml.safe_load(COMPOSE_PROD.read_text(encoding="utf-8")) or {}
    sensibles = {
        (service, nom): valeur
        for service, definition in (compose.get("services") or {}).items()
        for nom, valeur in _environnement(definition).items()
        if _est_sensible(nom)
    }

    assert ("echo", "DATABASE_URL") in sensibles, "echo doit lire sa base dans DATABASE_URL"
    for (service, nom), valeur in sensibles.items():
        assert INTERPOLATION_OBLIGATOIRE.search(valeur), f"{service}.{nom} : valeur littérale"
        reste = INTERPOLATION_OBLIGATOIRE.sub("", valeur)
        if nom.endswith("URL"):
            # Une URL peut garder schéma et hôte en clair, jamais ses identifiants.
            identifiants = re.match(r"^[a-z0-9+]+://([^@/]*)@", reste)
            assert identifiants is None or identifiants.group(1) in ("", ":"), f"{service}.{nom}"
        else:
            assert reste == "", f"{service}.{nom} : valeur littérale"


def test_le_modele_d_environnement_de_prod_n_a_que_des_valeurs_vides() -> None:
    assert MODELE_PROD.is_file(), "le modèle .env.prod.example doit exister"
    lignes = [
        ligne.strip()
        for ligne in MODELE_PROD.read_text(encoding="utf-8").splitlines()
        if ligne.strip() and not ligne.lstrip().startswith("#")
    ]

    assert lignes, ".env.prod.example ne déclare aucune variable"
    for ligne in lignes:
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*=", ligne), f"valeur non vide : {ligne}"
    assert not _ignore_par_git(".env.prod.example"), ".env.prod.example doit être suivi par Git"
    assert _ignore_par_git(".env.prod"), ".env.prod doit être ignoré par Git"
