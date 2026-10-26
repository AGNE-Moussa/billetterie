"""Configuration statique de Traefik pour la démo : HTTPS Let's Encrypt (BIL-F29, E3)."""

import json
import re
from pathlib import Path
from typing import Any

import yaml

RACINE = Path(__file__).resolve().parents[2]
TRAEFIK_PROD = RACINE / "infra" / "traefik" / "traefik.prod.yml"
COMPOSE_PROD = RACINE / "compose.prod.yaml"
KEYCLOAK_PROD = RACINE / "infra" / "consul" / "prod" / "keycloak.json"
ADRESSE_MAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _statique() -> dict[str, Any]:
    contenu: dict[str, Any] = yaml.safe_load(TRAEFIK_PROD.read_text(encoding="utf-8")) or {}
    return contenu


def _sans_commentaires(texte: str) -> str:
    return "\n".join(ligne for ligne in texte.splitlines() if not ligne.lstrip().startswith("#"))


def test_la_configuration_statique_de_prod_redirige_web_vers_websecure() -> None:
    points = _statique().get("entryPoints", {})
    web = points.get("web", {})
    redirection = ((web.get("http") or {}).get("redirections") or {}).get("entryPoint") or {}

    assert redirection.get("to") == "websecure"
    assert redirection.get("scheme") == "https"
    # Traefik v3 : redirection permanente par défaut, sauf `permanent: false`.
    assert redirection.get("permanent", True) is True
    assert (points.get("websecure") or {}).get("address") == ":443"


def test_le_point_d_entree_https_utilise_le_resolveur_let_s_encrypt() -> None:
    statique = _statique()
    websecure = (statique.get("entryPoints") or {}).get("websecure") or {}
    resolveur = ((websecure.get("http") or {}).get("tls") or {}).get("certResolver")
    resolveurs = statique.get("certificatesResolvers") or {}

    assert resolveur in resolveurs, "certResolver de websecure absent de certificatesResolvers"
    acme = resolveurs[resolveur].get("acme") or {}
    assert (acme.get("httpChallenge") or {}).get("entryPoint") == "web"


def test_l_adresse_acme_vient_de_l_environnement() -> None:
    textes = {
        fichier.name: _sans_commentaires(fichier.read_text(encoding="utf-8"))
        for fichier in (TRAEFIK_PROD, COMPOSE_PROD)
    }

    for nom, texte in textes.items():
        assert not ADRESSE_MAIL.findall(texte), f"adresse e-mail littérale dans {nom}"
    assert any("${ACME_EMAIL" in texte for texte in textes.values()), (
        "l'adresse ACME doit venir de la variable ACME_EMAIL"
    )


def test_le_routeur_keycloak_de_prod_exclut_la_console_d_administration() -> None:
    definition = json.loads(KEYCLOAK_PROD.read_text(encoding="utf-8"))
    regles = [
        tag.partition("=")[2]
        for tag in definition["service"]["tags"]
        if tag.startswith("traefik.http.routers.keycloak.rule=")
    ]

    assert len(regles) == 1
    assert "PathPrefix(`/auth`)" in regles[0]
    assert "!PathPrefix(`/auth/admin`)" in regles[0], f"/auth/admin routé : {regles[0]}"


def test_le_tableau_de_bord_de_traefik_est_coupe_en_prod() -> None:
    api = _statique().get("api") or {}

    assert api.get("insecure", False) is False
