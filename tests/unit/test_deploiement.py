"""Workflow de déploiement de la démo et absence de secret dans la CI (BIL-F29, E4, E5, CA3)."""

import json
import os
import re
import secrets
import subprocess
from pathlib import Path
from typing import Any

import yaml

RACINE = Path(__file__).resolve().parents[2]
WORKFLOWS = RACINE / ".github" / "workflows"
DEPLOIEMENT = WORKFLOWS / "deploiement.yml"
CI = WORKFLOWS / "ci.yml"
COMPOSE_PROD = RACINE / "compose.prod.yaml"
JOB_DEPLOIEMENT = "deployer"
DOSSIER_VPS = "/opt/billetterie"
PLATEFORMES = {"linux/amd64", "linux/arm64"}
DOCKERFILES = {"services/echo/Dockerfile", "infra/verificateur/Dockerfile", "frontend/Dockerfile"}
JOBS_DE_TEST = ("lint", "types", "unit", "integration", "contract", "frontend", "images")
EXPRESSION_SECRET = re.compile(r"\$\{\{\s*(secrets\.[A-Za-z0-9_]+|github\.token)\s*\}\}")
MATRICE = re.compile(r"\$\{\{\s*matrix\.(\w+)\s*\}\}")
MOTS_SENSIBLES = ("password", "key", "token", "ssh-key", "known_hosts")
MOTIF_TAG = "^sha-[0-9a-f]{7,40}$"
ENTREE_TAG = re.compile(r"(github\.event\.)?inputs\.tag\b")
# Faux `ssh` : chaque appel garde ses arguments et son entrée standard dans $SORTIE/appel.*.
FAUX_SSH = """#!/bin/sh
appel=$(mktemp -d "$SORTIE/appel.XXXXXX")
printf '%s' "$*" > "$appel/arguments"
cat > "$appel/entree"
"""


def _charger(fichier: Path) -> dict[str, Any]:
    contenu: dict[str, Any] = yaml.safe_load(fichier.read_text(encoding="utf-8")) or {}
    return contenu


def _declencheurs(workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML (YAML 1.1) lit la clé `on` comme le booléen True.
    on = workflow.get("on", workflow.get(True))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return dict.fromkeys(on)
    return dict(on or {})


def _jobs() -> dict[str, dict[str, Any]]:
    jobs: dict[str, dict[str, Any]] = _charger(DEPLOIEMENT).get("jobs") or {}
    return jobs


def _texte_etape(etape: dict[str, Any]) -> str:
    avec = etape.get("with") or {}
    morceaux = [etape.get("run", ""), avec.get("script", ""), avec.get("command", "")]
    return "\n".join(str(morceau) for morceau in morceaux if morceau)


def _texte_job(job: dict[str, Any]) -> str:
    return "\n".join(_texte_etape(etape) for etape in job.get("steps") or [])


def _etapes_de_construction() -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(job, étape) de chaque `docker/build-push-action`."""
    return [
        (job, etape)
        for job in _jobs().values()
        for etape in job.get("steps") or []
        if str(etape.get("uses", "")).startswith("docker/build-push-action")
    ]


def _constructions() -> list[dict[str, str]]:
    """Paramètres `with` de chaque construction, une par image, matrice résolue."""
    constructions: list[dict[str, str]] = []
    for job, etape in _etapes_de_construction():
        avec = {cle: str(valeur) for cle, valeur in (etape.get("with") or {}).items()}
        if not any(MATRICE.search(valeur) for valeur in avec.values()):
            constructions.append(avec)
            continue
        entrees = ((job.get("strategy") or {}).get("matrix") or {}).get("include") or []
        for entree in entrees:
            constructions.append(
                {
                    cle: MATRICE.sub(lambda m, e=entree: str(e.get(m.group(1), m.group(0))), v)
                    for cle, v in avec.items()
                }
            )
    return constructions


def _dockerfile(construction: dict[str, str]) -> str:
    contexte = construction.get("context", ".").rstrip("/")
    fichier = construction.get("file") or f"{contexte}/Dockerfile"
    return fichier.removeprefix("./")


def _parcourir(noeud: Any, chemin: str = "") -> list[tuple[str, str, Any]]:
    """(chemin, clé, valeur) de chaque entrée des sections `with` et `env` du workflow."""
    trouvees: list[tuple[str, str, Any]] = []
    if isinstance(noeud, dict):
        for cle, valeur in noeud.items():
            if cle in ("with", "env") and isinstance(valeur, dict):
                trouvees += [(f"{chemin}.{cle}", str(c), v) for c, v in valeur.items()]
            trouvees += _parcourir(valeur, f"{chemin}.{cle}")
    elif isinstance(noeud, list):
        for indice, element in enumerate(noeud):
            trouvees += _parcourir(element, f"{chemin}[{indice}]")
    return trouvees


# --- E5 : déclenchement et branche -------------------------------------------------------------


def test_le_deploiement_ne_se_declenche_que_manuellement() -> None:
    assert set(_declencheurs(_charger(DEPLOIEMENT))) == {"workflow_dispatch"}


def test_le_deploiement_ne_part_que_de_main() -> None:
    condition = str(_jobs()[JOB_DEPLOIEMENT].get("if", ""))

    assert re.search(r"github\.ref\s*==\s*'refs/heads/main'", condition), (
        f"le job {JOB_DEPLOIEMENT} doit être limité à refs/heads/main"
    )


# --- E5 : images ----------------------------------------------------------------------------------


def test_le_deploiement_construit_echo_le_verificateur_et_le_front_pour_amd64_et_arm64() -> None:
    constructions = _constructions()

    assert sorted(_dockerfile(c) for c in constructions) == sorted(DOCKERFILES)
    for construction in constructions:
        plateformes = {p.strip() for p in construction.get("platforms", "").split(",")}
        assert plateformes == PLATEFORMES, _dockerfile(construction)


def test_le_deploiement_publie_les_images_sur_ghcr() -> None:
    workflow = _charger(DEPLOIEMENT)
    etapes = _etapes_de_construction()
    assert etapes, "aucune étape docker/build-push-action"

    for construction in _constructions():
        assert construction.get("push", "").lower() == "true", _dockerfile(construction)
        tags = [t.strip() for t in re.split(r"[,\n]", construction.get("tags", "")) if t.strip()]
        assert tags, _dockerfile(construction)
        assert all(tag.startswith("ghcr.io/") for tag in tags), tags
        assert any("sha-" in tag for tag in tags), tags

    connexions = [
        etape.get("with") or {}
        for job in _jobs().values()
        for etape in job.get("steps") or []
        if str(etape.get("uses", "")).startswith("docker/login-action")
    ]
    assert any(
        avec.get("registry") == "ghcr.io"
        and re.fullmatch(
            r"\$\{\{\s*(secrets\.GITHUB_TOKEN|github\.token)\s*\}\}", str(avec.get("password"))
        )
        for avec in connexions
    ), "connexion à ghcr.io avec le jeton GITHUB_TOKEN absente"

    for job, _etape in etapes:
        permissions = job.get("permissions", workflow.get("permissions")) or {}
        assert permissions.get("packages") == "write"
        assert permissions.get("contents") == "read"


def test_le_deploiement_accepte_un_tag_pour_revenir_en_arriere() -> None:
    manuel = _declencheurs(_charger(DEPLOIEMENT)).get("workflow_dispatch") or {}
    entrees = manuel.get("inputs") or {}

    assert "tag" in entrees, "entrée `tag` absente de workflow_dispatch"
    assert entrees["tag"].get("required", False) is False
    etapes = _etapes_de_construction()
    assert etapes, "aucune étape docker/build-push-action"
    for job, etape in etapes:
        conditions = f"{job.get('if', '')} {etape.get('if', '')}"
        assert "inputs.tag" in conditions, "la construction doit être sautée si un tag est fourni"
    assert "inputs.tag" in json.dumps(_jobs()[JOB_DEPLOIEMENT]), "le tag fourni doit être déployé"


# --- E5 : migrations et SSH -----------------------------------------------------------------------


def test_le_deploiement_applique_les_migrations_avant_de_relancer_les_services() -> None:
    texte = _texte_job(_jobs()[JOB_DEPLOIEMENT])
    migration = re.search(
        r"alembic upgrade head|docker compose[^\n]*run --rm echo-migrations", texte
    )
    relance = re.search(r"docker compose[^\n]*\bup -d\b", texte)

    assert migration, "aucune étape ne lance les migrations"
    assert relance, "aucune étape ne lance docker compose up -d"
    assert migration.start() < relance.start(), "les migrations doivent précéder up -d"


def test_le_deploiement_relance_la_plateforme_par_ssh_avec_compose_pull_et_up() -> None:
    texte = _texte_job(_jobs()[JOB_DEPLOIEMENT])
    tirage = re.search(r"docker compose -f compose\.prod\.yaml pull", texte)
    relance = re.search(r"docker compose -f compose\.prod\.yaml[^\n]*\bup -d\b", texte)

    assert re.search(r"\bssh\b", texte), "la plateforme doit être relancée par SSH"
    assert DOSSIER_VPS in texte, f"les commandes doivent viser {DOSSIER_VPS}"
    assert tirage, "docker compose -f compose.prod.yaml pull absent"
    assert relance, "docker compose -f compose.prod.yaml up -d absent"
    assert tirage.start() < relance.start()


def test_la_cle_ssh_et_l_hote_viennent_des_secrets() -> None:
    brut = DEPLOIEMENT.read_text(encoding="utf-8")

    for secret in ("VPS_KNOWN_HOSTS", "VPS_CLE_SSH", "VPS_HOTE", "VPS_UTILISATEUR"):
        assert f"secrets.{secret}" in brut, f"le secret {secret} doit être lu dans secrets.*"
    assert "StrictHostKeyChecking=yes" in brut
    assert "StrictHostKeyChecking=no" not in brut
    assert "PRIVATE KEY" not in brut
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", brut), "adresse IP en clair"


def test_les_secrets_vont_au_vps_par_l_entree_standard() -> None:
    texte = _texte_job(_jobs()[JOB_DEPLOIEMENT])
    ecriture_distante = r"(cat\s*>|tee\b|/dev/stdin)[^\n]*\.env\.prod\b"
    par_tube = re.search(r"\|\s*ssh\b[^\n]*" + ecriture_distante, texte)
    par_redirection = re.search(r"\bssh\b[^\n]*" + ecriture_distante + r"[^\n]*<", texte)
    par_copie = re.search(r"\bscp\b[^\n]*\.env\.prod\b", texte)

    assert par_tube or par_redirection or par_copie, (
        ".env.prod doit être transmis par l'entrée standard de ssh (ou scp)"
    )
    assert not re.search(r"\bssh\b[^\n]*echo[^\n]*>\s*[^\n]*\.env\.prod", texte), (
        ".env.prod écrit en argument de commande ssh"
    )


# --- CA3 : secrets du workflow --------------------------------------------------------------------


def test_le_workflow_ne_contient_aucune_valeur_secrete_en_clair() -> None:
    sensibles = [
        (chemin, cle, valeur)
        for chemin, cle, valeur in _parcourir(_charger(DEPLOIEMENT))
        if any(mot in cle.lower() for mot in MOTS_SENSIBLES)
    ]

    assert sensibles, "le workflow doit recevoir ses identifiants (GHCR, SSH) par secrets"
    for chemin, cle, valeur in sensibles:
        assert EXPRESSION_SECRET.fullmatch(str(valeur).strip()), f"{chemin}.{cle}"


def test_le_workflow_n_interpole_aucun_secret_dans_un_script() -> None:
    noms_secrets = {
        cle
        for _chemin, cle, valeur in _parcourir(_charger(DEPLOIEMENT))
        if "secrets." in str(valeur)
    }
    scripts = [
        str(etape["run"])
        for job in _jobs().values()
        for etape in job.get("steps") or []
        if "run" in etape
    ]

    assert noms_secrets, "les secrets doivent passer aux scripts par env:"
    for script in scripts:
        assert "secrets." not in script, script
        assert not re.search(r"\bset\s+-[a-wyz]*x", script), "set -x dans un script"
        assert not re.search(r"^\s*(printenv|env)\s*$", script, re.MULTILINE), script
        for nom in noms_secrets:
            assert not re.search(rf"\becho\b[^\n]*\$\{{?{nom}\b", script), f"echo de {nom}"


# --- E4 : front de prod ---------------------------------------------------------------------------


def test_le_front_de_prod_n_embarque_aucune_url_d_api_ou_de_keycloak_absolue() -> None:
    for fichier in (DEPLOIEMENT, COMPOSE_PROD):
        brut = fichier.read_text(encoding="utf-8")
        assert "VITE_API_URL" not in brut, fichier.name
        assert "VITE_KEYCLOAK_URL" not in brut, fichier.name


# --- E5 : la CI de test reste sans secret ---------------------------------------------------------


def test_les_jobs_de_test_de_la_ci_ne_recoivent_aucun_secret() -> None:
    jobs = _charger(CI)["jobs"]

    for nom in JOBS_DE_TEST:
        assert nom in jobs, nom
        assert "secrets." not in json.dumps(jobs[nom]), nom


# --- Validation 2 : entrée tag, .env.prod -------------------------------------------------------


def _etapes_deploiement() -> list[dict[str, Any]]:
    etapes: list[dict[str, Any]] = _jobs()[JOB_DEPLOIEMENT].get("steps") or []
    return etapes


def test_l_entree_tag_est_validee_avant_tout_usage() -> None:
    etapes = _etapes_deploiement()
    usages = [i for i, etape in enumerate(etapes) if ENTREE_TAG.search(json.dumps(etape))]
    validations = [i for i, etape in enumerate(etapes) if MOTIF_TAG in str(etape.get("run", ""))]

    assert usages, f"le job {JOB_DEPLOIEMENT} doit lire l'entrée tag"
    assert validations, f"aucune étape ne valide l'entrée tag contre {MOTIF_TAG}"
    assert validations[0] <= usages[0], "l'entrée tag est utilisée avant d'être validée"
    if validations[0] == usages[0]:
        script = str(etapes[usages[0]]["run"])
        if "GITHUB_OUTPUT" in script:
            assert script.index(MOTIF_TAG) < script.index("GITHUB_OUTPUT"), (
                "le tag est publié en sortie avant d'être validé"
            )
    for nom, job in _jobs().items():
        for etape in job.get("steps") or []:
            script = str(etape.get("run", ""))
            assert not re.search(r"\$\{\{[^}]*inputs\.tag", script), (
                f"{nom} : inputs.tag interpolé dans un run:"
            )
    assert any(ENTREE_TAG.search(json.dumps(etape.get("env") or {})) for etape in etapes), (
        "l'entrée tag doit passer aux scripts par env:"
    )


def test_les_valeurs_de_env_prod_sont_entre_guillemets_simples(
    tmp_path: Path, shell_posix: str, path_posix: str
) -> None:
    etape = next(
        (e for e in _etapes_deploiement() if ".env.prod" in str(e.get("run", "")) and e.get("env")),
        None,
    )
    assert etape is not None, "aucune étape n'écrit .env.prod depuis env:"
    # Valeurs synthétiques ; le `$` ne doit jamais être interprété une fois dans .env.prod.
    valeurs = {nom: f"v{secrets.token_urlsafe(12)}$PAS_INTERPOLE" for nom in etape["env"]}
    outils = tmp_path / "outils"
    sortie = tmp_path / "sortie"
    outils.mkdir()
    sortie.mkdir()
    faux_ssh = outils / "ssh"
    faux_ssh.write_text(FAUX_SSH, encoding="utf-8", newline="\n")
    faux_ssh.chmod(0o755)
    script = tmp_path / "ecrire_env_prod.sh"
    script.write_text(str(etape["run"]), encoding="utf-8", newline="\n")
    environnement = {
        **os.environ,
        **valeurs,
        "SORTIE": sortie.as_posix(),
        "PATH": f"{outils}{os.pathsep}{path_posix}",
    }

    resultat = subprocess.run(
        [shell_posix, "-e", script.as_posix()],
        env=environnement,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert resultat.returncode == 0, resultat.stderr
    appels = [
        appel
        for appel in sortie.iterdir()
        if ".env.prod" in (appel / "arguments").read_text(encoding="utf-8")
    ]
    assert len(appels) == 1, "un seul appel ssh doit écrire .env.prod"
    lignes = [
        ligne
        for ligne in (appels[0] / "entree").read_text(encoding="utf-8").splitlines()
        if ligne.strip()
    ]
    assert lignes, ".env.prod vide"
    for ligne in lignes:
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*='[^']*'", ligne), f"valeur sans guillemets : {ligne}"
    ecrites = dict(ligne.split("=", 1) for ligne in lignes)
    for nom, valeur in valeurs.items():
        if nom in ecrites:
            assert ecrites[nom] == f"'{valeur}'", nom


def test_env_prod_recoit_des_droits_600_explicites() -> None:
    texte = _texte_job(_jobs()[JOB_DEPLOIEMENT])

    assert re.search(r"chmod 0?600 (/opt/billetterie/)?\.env\.prod\b", texte), (
        f"chmod 600 explicite absent pour {DOSSIER_VPS}/.env.prod"
    )
