"""Script de démarrage de Traefik en démo : DOMAINE validé avant tout usage (BIL-F29, point 9).

Le script est exécuté pour de vrai par un `sh` POSIX, sans Docker : ses chemins fixes
(/etc/traefik/) sont redirigés vers un dossier temporaire et `traefik` est remplacé par un faux
binaire qui ne fait que laisser une trace de son lancement. Les outils POSIX (`sed`, `cat`) sont
ceux de l'environnement du `sh` choisi (fixture `path_posix`).
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
SCRIPT = RACINE / "infra" / "traefik" / "demarrer-prod.sh"
TRAEFIK_PROD = RACINE / "infra" / "traefik" / "traefik.prod.yml"
DOMAINE_VALIDE = "demo.exemple.test"
FAUX_TRAEFIK = """#!/bin/sh
: > "$MARQUEUR"
"""
COMMANDE_INTROUVABLE = 127


@dataclass(frozen=True)
class Lancement:
    code: int
    erreurs: str
    traefik_lance: bool

    @property
    def environnement_casse(self) -> bool:
        """Le script a planté faute d'outil : ce n'est pas un refus du DOMAINE."""
        return self.code == COMMANDE_INTROUVABLE or "not found" in self.erreurs


def _lancer(dossier: Path, shell_posix: str, path_posix: str, domaine: str) -> Lancement:
    """Exécute le script avec ce DOMAINE dans `dossier` (créé)."""
    configuration = dossier / "etc-traefik"
    outils = dossier / "outils"
    configuration.mkdir(parents=True)
    outils.mkdir()
    (configuration / "traefik.prod.yml").write_text(
        TRAEFIK_PROD.read_text(encoding="utf-8"), encoding="utf-8", newline="\n"
    )
    faux = outils / "traefik"
    faux.write_text(FAUX_TRAEFIK, encoding="utf-8", newline="\n")
    faux.chmod(0o755)
    script = dossier / "demarrer-prod.sh"
    script.write_text(
        SCRIPT.read_text(encoding="utf-8").replace("/etc/traefik/", f"{configuration.as_posix()}/"),
        encoding="utf-8",
        newline="\n",
    )
    marqueur = dossier / "traefik-lance"
    environnement = {
        **os.environ,
        "DOMAINE": domaine,
        "ACME_EMAIL": "acme.test@exemple.test",
        "ACME_CA_SERVER": "https://acme.exemple.test/directory",
        "MARQUEUR": marqueur.as_posix(),
        "PATH": f"{outils}{os.pathsep}{path_posix}",
    }
    resultat = subprocess.run(
        [shell_posix, script.as_posix()],
        env=environnement,
        cwd=dossier,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return Lancement(resultat.returncode, resultat.stderr, marqueur.exists())


def _verifier_temoin(dossier: Path, shell_posix: str, path_posix: str) -> None:
    temoin = _lancer(dossier, shell_posix, path_posix, DOMAINE_VALIDE)
    assert not temoin.environnement_casse, f"environnement POSIX cassé : {temoin.erreurs}"
    assert temoin.code == 0, temoin.erreurs
    assert temoin.traefik_lance


def _verifier_refus(lancement: Lancement, domaine: str) -> None:
    assert not lancement.environnement_casse, (
        f"le script a planté (code {lancement.code}) au lieu de refuser : {lancement.erreurs}"
    )
    assert lancement.code != 0, f"DOMAINE {domaine!r} accepté"
    assert not lancement.traefik_lance, "Traefik lancé avec un DOMAINE invalide"


def test_un_domaine_valide_demarre_traefik(
    tmp_path: Path, shell_posix: str, path_posix: str
) -> None:
    # Témoin : sans lui, un refus des domaines piégés pourrait venir du montage du test.
    _verifier_temoin(tmp_path, shell_posix, path_posix)


def test_un_domaine_vide_est_refuse(tmp_path: Path, shell_posix: str, path_posix: str) -> None:
    _verifier_temoin(tmp_path / "temoin", shell_posix, path_posix)

    _verifier_refus(_lancer(tmp_path / "vide", shell_posix, path_posix, ""), "")


@pytest.mark.parametrize(
    "domaine",
    [
        "exemple.test; touch piege",
        "exemple.test/chemin",
        "demo exemple.test",
        "demo.exemple.test|x",
        "Demo.Exemple.Test",
        "demo.exemple.test$(id)",
    ],
)
def test_un_domaine_hors_des_caracteres_autorises_est_refuse(
    tmp_path: Path, shell_posix: str, path_posix: str, domaine: str
) -> None:
    _verifier_temoin(tmp_path / "temoin", shell_posix, path_posix)

    dossier = tmp_path / "piege-tente"
    _verifier_refus(_lancer(dossier, shell_posix, path_posix, domaine), domaine)
    assert not (dossier / "piege").exists()
