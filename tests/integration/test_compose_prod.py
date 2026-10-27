"""Plateforme de démo (BIL-F29) : compose.prod.yaml résolu par `docker compose config`.

Le fichier d'environnement est synthétique (conftest : valeurs_env_prod) : aucun secret GitHub,
aucune URL Neon, jamais le vrai domaine.
"""

import json
import re
from pathlib import Path
from typing import Any

import yaml

DOMAINE = "demo.exemple.test"
EMETTEUR = f"https://{DOMAINE}/auth/realms/billetterie"
RACINE = Path(__file__).resolve().parents[2]
TRAEFIK_PROD = RACINE / "infra" / "traefik" / "traefik.prod.yml"
CONSUL_PROD = RACINE / "infra" / "consul" / "prod"
SERVICES_RETENUS = {
    "traefik",
    "consul",
    "verificateur",
    "keycloak",
    "rabbitmq",
    "echo",
    "echo-migrations",
    "frontend",
}
SERVICES_MAISON = ("echo", "verificateur", "frontend")
BUDGET_MEMOIRE = 3072 * 1024 * 1024
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


# --- E1 : compose.prod.yaml valide et sans PostgreSQL local ---------------------------------


def test_la_configuration_de_prod_est_valide_avec_un_environnement_synthetique(
    compose_prod: Any, valeurs_env_prod: dict[str, str]
) -> None:
    resultat = compose_prod(valeurs_env_prod, ["--quiet"])

    assert resultat.returncode == 0, resultat.stderr
    assert resultat.stderr.strip() == ""


def test_sans_database_url_la_configuration_de_prod_est_refusee(
    compose_prod: Any, valeurs_env_prod: dict[str, str]
) -> None:
    sans_base = {nom: v for nom, v in valeurs_env_prod.items() if nom != "ECHO_DATABASE_URL"}

    resultat = compose_prod(sans_base, ["--quiet"])

    assert resultat.returncode != 0, "La configuration est acceptée sans ECHO_DATABASE_URL"
    assert "ECHO_DATABASE_URL" in resultat.stderr


def test_compose_prod_exige_le_secret_du_revendeur(
    compose_prod: Any, valeurs_env_prod: dict[str, str]
) -> None:
    """BIL-003, C1 : le secret du client revendeur-test vient de .env.prod, jamais du dépôt."""
    sans_secret = {
        nom: v for nom, v in valeurs_env_prod.items() if nom != "KEYCLOAK_REVENDEUR_SECRET"
    }

    refuse = compose_prod(sans_secret, ["--quiet"])
    accepte = compose_prod(valeurs_env_prod, ["--format", "json"])

    assert refuse.returncode != 0, "La configuration est acceptée sans KEYCLOAK_REVENDEUR_SECRET"
    assert "KEYCLOAK_REVENDEUR_SECRET" in refuse.stderr, refuse.stderr
    assert accepte.returncode == 0, accepte.stderr
    environnement = _environnement(json.loads(accepte.stdout), "keycloak")
    assert (
        environnement.get("KEYCLOAK_REVENDEUR_SECRET")
        == valeurs_env_prod["KEYCLOAK_REVENDEUR_SECRET"]
    )


def test_la_prod_ne_contient_aucun_service_postgres(config_prod: Any) -> None:
    services = _services(config_prod)

    assert not [nom for nom, s in services.items() if s.get("image", "").startswith("postgres")]
    assert "postgres-data" not in (config_prod.get("volumes") or {})
    assert not [nom for nom, s in services.items() if "postgres" in (s.get("depends_on") or {})]
    # Garde-fou : la configuration contient bien la plateforme, pas seulement la gateway.
    assert {"echo", "keycloak"} <= set(services), sorted(services)


def test_les_services_lisent_leur_base_dans_database_url(
    config_prod: Any, valeurs_env_prod: dict[str, str]
) -> None:
    for service in ("echo", "echo-migrations"):
        assert (
            _environnement(config_prod, service).get("DATABASE_URL")
            == valeurs_env_prod["ECHO_DATABASE_URL"]
        ), service
    for nom in _services(config_prod):
        for valeur in _environnement(config_prod, nom).values():
            assert "@postgres:" not in (valeur or ""), nom


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
    assert not services & {"prometheus", "grafana", "mailpit", "tempo", "redis"}


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

    # Conteneurs ponctuels compris (echo-migrations) ; chaque conteneur retenu doit être compté.
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


def test_le_verificateur_et_echo_attendent_l_emetteur_du_domaine(config_prod: Any) -> None:
    for service in ("verificateur", "echo"):
        assert _environnement(config_prod, service).get("JWT_EMETTEUR") == EMETTEUR, service


def test_keycloak_de_prod_lit_sa_base_dans_l_environnement(
    config_prod: Any, valeurs_env_prod: dict[str, str]
) -> None:
    environnement = _environnement(config_prod, "keycloak")

    for variable in ("KC_DB_URL", "KC_DB_USERNAME", "KC_DB_PASSWORD"):
        nom_secret = variable.replace("KC_", "KEYCLOAK_", 1)
        assert environnement.get(variable) == valeurs_env_prod[nom_secret], variable
    assert "postgres:5432" not in environnement.get("KC_DB_URL", "")


def test_le_front_de_prod_est_route_sur_la_racine_hors_api_et_auth(config_prod: Any) -> None:
    dossier = _dossier_consul_monte(config_prod)

    assert dossier is not None, "Aucun dossier de définitions monté dans le service consul"
    tags = _tags(dossier, "frontend")
    routeur = "traefik.http.routers.frontend"
    assert f"{routeur}.rule=PathPrefix(`/`) && !PathPrefix(`/api`) && !PathPrefix(`/auth`)" in tags
    assert f"{routeur}.priority=1" in tags
    assert f"{routeur}.middlewares=public@file" in tags
