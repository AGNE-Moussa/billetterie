"""Plateforme de démo (BIL-F29, BIL-017) : compose.prod.yaml résolu par `docker compose config`.

BIL-017 : toute la plateforme sur une VM (Oracle Cloud Always Free, 24 Go) : PostgreSQL, Redis
et RabbitMQ sur la VM (plus de Neon), une instance par service, e-mails par un relais SMTP
authentifié. Le fichier d'environnement est synthétique (conftest : valeurs_env_prod) : aucun
secret, jamais le vrai domaine.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

DOMAINE = "demo.exemple.test"
EMETTEUR = f"https://{DOMAINE}/auth/realms/billetterie"
RACINE = Path(__file__).resolve().parents[2]
TRAEFIK_PROD = RACINE / "infra" / "traefik" / "traefik.prod.yml"
CONSUL_PROD = RACINE / "infra" / "consul" / "prod"
SERVICES_RETENUS = {
    "postgres",
    "redis",
    "rabbitmq",
    "traefik",
    "consul",
    "keycloak",
    "verificateur",
    "echo",
    "echo-migrations",
    "catalogue",
    "catalogue-migrations",
    "billets",
    "billets-migrations",
    "commandes",
    "commandes-migrations",
    "file-attente",
    "paiements",
    "paiements-migrations",
    "notifications",
    "notifications-migrations",
    "frontend",
}
SERVICES_PYTHON = (
    "echo",
    "catalogue",
    "billets",
    "commandes",
    "file-attente",
    "paiements",
    "notifications",
)
SERVICES_MAISON = ("verificateur", "frontend", *SERVICES_PYTHON)
# VM Always Free : 24 Go ; la moitié au plus pour les limites (système, constructions d'images).
BUDGET_MEMOIRE = 12 * 1024**3
UNITES = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}


def _services(config: Any) -> dict[str, Any]:
    services: dict[str, Any] = config.get("services", {})
    return services


def _environnement(config: Any, service: str) -> dict[str, str]:
    environnement: dict[str, str] = _services(config).get(service, {}).get("environment") or {}
    return environnement


def _limite_memoire(definition: dict[str, Any]) -> int | None:
    memoire = (definition.get("deploy") or {}).get("resources", {}).get("limits", {}).get("memory")
    return None if memoire is None else int(memoire)


def _dossier_consul_monte(config: Any) -> Path | None:
    """Dossier de définitions Consul monté dans le service consul de prod."""
    for volume in _services(config).get("consul", {}).get("volumes", []):
        if volume.get("type") == "bind" and Path(volume["source"]).is_dir():
            return Path(volume["source"])
    return None


def _tags(dossier: Path, service: str) -> list[str]:
    definition = json.loads((dossier / f"{service}.json").read_text(encoding="utf-8"))
    tags: list[str] = definition["service"]["tags"]
    return tags


# --- E1 : compose.prod.yaml valide, données sur la VM ---------------------------------------


def test_la_configuration_de_prod_est_valide_avec_un_environnement_synthetique(
    compose_prod: Any, valeurs_env_prod: dict[str, str]
) -> None:
    resultat = compose_prod(valeurs_env_prod, ["--quiet"])

    assert resultat.returncode == 0, resultat.stderr
    assert resultat.stderr.strip() == ""


@pytest.mark.parametrize(
    "variable",
    ["CATALOGUE_DB_PASSWORD", "QR_CLE_SIGNATURE", "SMTP_MOT_DE_PASSE", "KEYCLOAK_REVENDEUR_SECRET"],
)
def test_sans_un_secret_obligatoire_la_configuration_de_prod_est_refusee(
    compose_prod: Any, valeurs_env_prod: dict[str, str], variable: str
) -> None:
    sans = {nom: v for nom, v in valeurs_env_prod.items() if nom != variable}

    resultat = compose_prod(sans, ["--quiet"])

    assert resultat.returncode != 0, f"La configuration est acceptée sans {variable}"
    assert variable in resultat.stderr, resultat.stderr


def test_compose_prod_transmet_le_secret_du_revendeur_a_keycloak(
    config_prod: Any, valeurs_env_prod: dict[str, str]
) -> None:
    """BIL-003, C1 : le secret du client revendeur-test vient de .env.prod, jamais du dépôt."""
    environnement = _environnement(config_prod, "keycloak")

    assert (
        environnement.get("KEYCLOAK_REVENDEUR_SECRET")
        == valeurs_env_prod["KEYCLOAK_REVENDEUR_SECRET"]
    )


def test_postgresql_tourne_sur_la_vm_avec_un_volume_et_l_initialisation_des_bases(
    config_prod: Any,
) -> None:
    postgres = _services(config_prod).get("postgres", {})
    cibles = {volume["target"] for volume in postgres.get("volumes", [])}

    assert postgres.get("image", "").startswith("postgres:16")
    assert "postgres-data" in (config_prod.get("volumes") or {})
    assert {"/var/lib/postgresql/data", "/docker-entrypoint-initdb.d"} <= cibles


def test_chaque_service_lit_sa_propre_base_avec_son_propre_mot_de_passe(
    config_prod: Any, valeurs_env_prod: dict[str, str]
) -> None:
    for service in ("echo", "catalogue", "billets", "commandes", "paiements", "notifications"):
        mot_de_passe = valeurs_env_prod[f"{service.upper()}_DB_PASSWORD"]
        attendu = f"postgresql+asyncpg://{service}:{mot_de_passe}@postgres:5432/{service}"
        for conteneur in (service, f"{service}-migrations"):
            assert _environnement(config_prod, conteneur).get("DATABASE_URL") == attendu, conteneur


def test_la_prod_tire_les_images_de_ghcr_sans_construire(config_prod: Any) -> None:
    services = _services(config_prod)

    for nom in SERVICES_MAISON:
        assert nom in services, f"Service {nom} absent de compose.prod.yaml"
        image = services[nom].get("image", "")
        assert image.startswith("ghcr.io/"), (nom, image)
        assert image.endswith(":sha-0000000"), (nom, image)
        assert "build" not in services[nom], nom


def test_la_prod_ne_garde_que_les_conteneurs_retenus(config_prod: Any) -> None:
    services = set(_services(config_prod))

    assert services == SERVICES_RETENUS
    assert not services & {"prometheus", "grafana", "mailpit", "tempo"}


def test_seul_traefik_publie_des_ports_et_seulement_80_et_443(config_prod: Any) -> None:
    services = _services(config_prod)

    publies = {int(port["published"]) for port in services.get("traefik", {}).get("ports", [])}
    assert publies == {80, 443}
    assert not [nom for nom, s in services.items() if nom != "traefik" and s.get("ports")]


# --- E2 : limites mémoire --------------------------------------------------------------------


def test_chaque_conteneur_de_prod_a_une_limite_memoire(config_prod: Any) -> None:
    services = _services(config_prod)

    sans_limite = [nom for nom, s in services.items() if _limite_memoire(s) is None]
    assert not sans_limite, sans_limite
    assert set(services) == SERVICES_RETENUS


def test_le_total_des_limites_memoire_tient_dans_le_budget_de_la_demo(config_prod: Any) -> None:
    services = _services(config_prod)
    limites = {nom: _limite_memoire(s) for nom, s in services.items()}

    # Conteneurs ponctuels compris (migrations) ; chaque conteneur retenu doit être compté.
    assert set(limites) == SERVICES_RETENUS
    assert None not in limites.values(), limites
    assert sum(limite or 0 for limite in limites.values()) <= BUDGET_MEMOIRE, limites


def test_la_heap_de_keycloak_tient_dans_sa_limite_memoire(config_prod: Any) -> None:
    keycloak = _services(config_prod).get("keycloak", {})
    options = _environnement(config_prod, "keycloak").get("JAVA_OPTS_KC_HEAP") or ""
    xmx = re.search(r"-Xmx(\d+)([kKmMgG]?)", options)
    limite = _limite_memoire(keycloak)

    assert xmx, f"Aucun -Xmx dans JAVA_OPTS_KC_HEAP : {options!r}"
    assert limite is not None
    heap = int(xmx.group(1)) * UNITES[xmx.group(2).lower()]
    assert heap < limite


# --- E3 : TLS et points d'entrée -------------------------------------------------------------


def test_les_certificats_acme_sont_stockes_sur_un_volume_persistant(config_prod: Any) -> None:
    statique = yaml.safe_load(TRAEFIK_PROD.read_text(encoding="utf-8")) or {}
    resolveurs = statique.get("certificatesResolvers") or {}
    volumes_nommes = [
        volume["target"].rstrip("/")
        for volume in _services(config_prod).get("traefik", {}).get("volumes", [])
        if volume.get("type") == "volume"
    ]

    assert resolveurs, "Aucun résolveur de certificats dans traefik.prod.yml"
    for nom, resolveur in resolveurs.items():
        stockage = resolveur["acme"]["storage"]
        assert any(stockage.startswith(f"{cible}/") for cible in volumes_nommes), (
            nom,
            stockage,
            volumes_nommes,
        )


def test_les_definitions_consul_de_keycloak_et_du_front_suivent_le_point_d_entree_de_prod(
    config_prod: Any,
) -> None:
    dossier = _dossier_consul_monte(config_prod)

    assert dossier is not None, "Aucun dossier de définitions monté dans le service consul"
    assert dossier.resolve() == CONSUL_PROD.resolve()
    for service in ("keycloak", "frontend"):
        tags = _tags(dossier, service)
        assert f"traefik.http.routers.{service}.entrypoints=websecure" in tags, tags


# --- E4 : Keycloak en mode production, front sur / -------------------------------------------


def test_keycloak_de_prod_demarre_en_mode_production(config_prod: Any) -> None:
    commande = _services(config_prod).get("keycloak", {}).get("command") or []

    assert commande, "Aucune commande Keycloak dans compose.prod.yaml"
    assert commande[0] == "start"
    assert "start-dev" not in commande


def test_keycloak_de_prod_publie_l_emetteur_https_du_domaine_sous_auth(config_prod: Any) -> None:
    environnement = _environnement(config_prod, "keycloak")

    assert environnement.get("KC_HTTP_RELATIVE_PATH") == "/auth"
    assert environnement.get("KC_HOSTNAME") == f"https://{DOMAINE}/auth"
    assert environnement.get("KC_PROXY_HEADERS") == "xforwarded"


def test_le_verificateur_et_les_services_attendent_l_emetteur_du_domaine(
    config_prod: Any,
) -> None:
    for service in ("verificateur", *SERVICES_PYTHON):
        assert _environnement(config_prod, service).get("JWT_EMETTEUR") == EMETTEUR, service


def test_les_services_annoncent_leurs_routes_en_https_et_l_hote_des_revendeurs(
    config_prod: Any,
) -> None:
    for service in SERVICES_PYTHON:
        environnement = _environnement(config_prod, service)
        assert environnement.get("TRAEFIK_POINT_ENTREE") == "websecure", service
        assert environnement.get("HOTE_PARTENAIRES") == f"partenaires.{DOMAINE}", service


def test_keycloak_de_prod_lit_sa_base_sur_la_vm(
    config_prod: Any, valeurs_env_prod: dict[str, str]
) -> None:
    environnement = _environnement(config_prod, "keycloak")

    assert environnement.get("KC_DB_URL") == "jdbc:postgresql://postgres:5432/keycloak"
    assert environnement.get("KC_DB_USERNAME") == "keycloak"
    assert environnement.get("KC_DB_PASSWORD") == valeurs_env_prod["KEYCLOAK_DB_PASSWORD"]


def test_commandes_appelle_la_gateway_en_https_par_l_alias_reseau_de_traefik(
    config_prod: Any,
) -> None:
    """http://traefik serait redirigé en HTTPS vers un hôte sans certificat : Commandes passe par
    https://<domaine>, que l'alias réseau de Traefik résout sans sortir de la VM."""
    reseaux = _services(config_prod).get("traefik", {}).get("networks", {})

    assert _environnement(config_prod, "commandes").get("URL_GATEWAY") == f"https://{DOMAINE}"
    assert {DOMAINE, f"partenaires.{DOMAINE}"} <= set(reseaux["billetterie"]["aliases"])


def test_les_e_mails_partent_par_un_relais_smtp_authentifie_en_starttls(
    config_prod: Any, valeurs_env_prod: dict[str, str]
) -> None:
    notifications = _environnement(config_prod, "notifications")
    keycloak = _environnement(config_prod, "keycloak")

    assert notifications.get("SMTP_STARTTLS") == "true"
    assert notifications.get("SMTP_PORT") == "587"
    assert notifications.get("SMTP_MOT_DE_PASSE") == valeurs_env_prod["SMTP_MOT_DE_PASSE"]
    assert keycloak.get("KEYCLOAK_SMTP_STARTTLS") == "true"
    assert keycloak.get("KEYCLOAK_SMTP_AUTH") == "true"
    assert keycloak.get("KEYCLOAK_SMTP_HOTE") == valeurs_env_prod["SMTP_HOTE"]


def test_le_front_vercel_est_autorise_en_cors_et_dans_les_redirections_keycloak(
    config_prod: Any, valeurs_env_prod: dict[str, str]
) -> None:
    vercel = valeurs_env_prod["URL_FRONT_VERCEL"]

    origines = _environnement(config_prod, "traefik").get("CORS_ORIGINS", "").split(",")
    assert origines == [f"https://{DOMAINE}", vercel]
    assert _environnement(config_prod, "keycloak").get("KEYCLOAK_URL_FRONT_VERCEL") == vercel


def test_le_front_de_prod_est_route_sur_la_racine_hors_api_et_auth(config_prod: Any) -> None:
    dossier = _dossier_consul_monte(config_prod)

    assert dossier is not None, "Aucun dossier de définitions monté dans le service consul"
    tags = _tags(dossier, "frontend")
    routeur = "traefik.http.routers.frontend"
    assert f"{routeur}.rule=PathPrefix(`/`) && !PathPrefix(`/api`) && !PathPrefix(`/auth`)" in tags
    assert f"{routeur}.priority=1" in tags
    assert f"{routeur}.middlewares=public@file" in tags
