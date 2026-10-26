"""Conteneurs partagés par les tests d'intégration."""

import json
import os
import secrets
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NamedTuple

import httpx
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network

IMAGE_CONSUL = "hashicorp/consul:1.21.5"
IMAGE_FAUX_SERVICE = "hashicorp/http-echo:1.0"
IMAGE_TRAEFIK = "traefik:v3.5.3"
IMAGE_WHOAMI = "traefik/whoami:v1.11.0"
RACINE = Path(__file__).resolve().parents[2]
DOSSIER_TRAEFIK = RACINE / "infra" / "traefik"
COMPOSE_PROD = RACINE / "compose.prod.yaml"
ORIGINE_FRONT = "http://localhost:5173"
DOMAINE_DEMO = "demo.exemple.test"

ExecuterComposeProd = Callable[[dict[str, str], list[str]], subprocess.CompletedProcess[str]]
COMPOSE_LOCAL = RACINE / "compose.yaml"


class Squelette(NamedTuple):
    """Un service métier de BIL-001 (docs/test-plans/BIL-001.md, données communes)."""

    nom: str
    paquet: str
    ressource: str
    instances: tuple[str, ...]

    @property
    def migrations(self) -> str:
        return f"{self.nom}-migrations"

    @property
    def variable_mot_de_passe(self) -> str:
        return f"{self.nom.upper()}_DB_PASSWORD"


# Table unique des squelettes : tout test qui prend un argument `squelette` est paramétré
# dessus (pytest_generate_tests ci-dessous), aucune copie par service.
SERVICES = (
    Squelette("catalogue", "billetterie-catalogue", "events", ("catalogue-1",)),
    Squelette("billets", "billetterie-billets", "seats", ("billets-1", "billets-2")),
    Squelette("commandes", "billetterie-commandes", "orders", ("commandes-1", "commandes-2")),
    Squelette("paiements", "billetterie-paiements", "payments", ("paiements-1",)),
    Squelette("notifications", "billetterie-notifications", "notifications", ("notifications-1",)),
)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    # Portée module : les conteneurs d'un service (base, Consul) sont partagés par ses tests.
    if "squelette" in metafunc.fixturenames:
        metafunc.parametrize(
            "squelette", SERVICES, ids=[service.nom for service in SERVICES], scope="module"
        )


@pytest.fixture(scope="session")
def services_metier() -> tuple[Squelette, ...]:
    """La table SERVICES, pour les tests qui portent sur les cinq services à la fois."""
    return SERVICES


# Échéance d'une étape d'attente (démarrage de conteneur, migration, Consul, gateway) : large
# pour un poste lent, mais finie (pytest-timeout n'est pas dans le projet).
DELAI_ETAPE = 120.0

ExecuterBorne = Callable[[str, float, Callable[[], Any], Callable[[], str]], Any]


def _observer(observe: Callable[[], str]) -> str:
    """Dernier état observé, sans jamais masquer l'échec d'origine."""
    try:
        return observe()
    except Exception as erreur:  # noqa: BLE001 : diagnostic seulement
        return f"(observation impossible : {erreur!r})"


def executer_borne(
    etape: str, delai: float, fonction: Callable[[], Any], observe: Callable[[], str]
) -> Any:
    """Appel bloquant (Docker, build d'image) dans un fil, avec une échéance mesurée.

    Au-delà de `delai`, AssertionError qui nomme l'étape et donne le dernier état observé ;
    le fil bloqué est abandonné : fil démon, jamais rejoint, même à la fin de la session
    (ceux d'un ThreadPoolExecutor seraient attendus à la sortie de Python).
    """
    resultat: list[Any] = []
    erreur: list[BaseException] = []

    def executer() -> None:
        try:
            resultat.append(fonction())
        except BaseException as exception:  # noqa: BLE001 : relevée dans le fil appelant
            erreur.append(exception)

    debut = time.monotonic()
    fil = threading.Thread(target=executer, name=f"etape {etape}", daemon=True)
    fil.start()
    fil.join(timeout=max(0.0, debut + delai - time.monotonic()))
    if fil.is_alive():
        duree = time.monotonic() - debut
        raise AssertionError(
            f"{etape} : échéance de {delai:.0f} s dépassée ({duree:.0f} s mesurées) ; "
            f"dernier état observé : {_observer(observe)}"
        )
    if erreur:
        raise erreur[0]
    return resultat[0]


def journal_conteneur(conteneur: DockerContainer, lignes: int = 30) -> str:
    """Dernières lignes du journal d'un conteneur (sortie et erreurs), pour les diagnostics."""
    if conteneur._container is None:  # noqa: SLF001 : conteneur jamais créé
        return "(conteneur non créé)"
    sortie, erreurs = conteneur.get_logs()
    texte = (sortie + erreurs).decode("utf-8", errors="replace").splitlines()
    return "\n".join(texte[-lignes:]) or "(journal vide)"


@pytest.fixture(scope="session")
def borne() -> ExecuterBorne:
    """executer_borne, pour les fixtures et tests qui démarrent leurs propres conteneurs."""
    return executer_borne


@pytest.fixture(scope="session")
def journal() -> Callable[[DockerContainer], str]:
    """journal_conteneur, pour les messages d'échec des tests."""
    return journal_conteneur


def url_depuis_hote(conteneur: DockerContainer, port: int) -> str:
    """URL d'un port publié, vue depuis la machine qui lance les tests."""
    hote = conteneur.get_container_host_ip()
    # Sous Windows, « localhost » passe d'abord par IPv6 (::1) et Docker Desktop coupe
    # alors les connexions après la première requête : on force IPv4.
    if hote == "localhost":
        hote = "127.0.0.1"
    return f"http://{hote}:{conteneur.get_exposed_port(port)}"


@pytest.fixture(scope="module")
def reseau() -> Iterator[Network]:
    """Réseau Docker commun : Consul doit pouvoir appeler le faux service par son nom."""
    with Network() as reseau:
        yield reseau


@pytest.fixture(scope="module")
def consul_url(reseau: Network) -> Iterator[str]:
    """Démarre un agent Consul en mode dev et renvoie son URL vue depuis l'hôte."""
    consul = (
        DockerContainer(IMAGE_CONSUL)
        .with_command("agent -dev -client=0.0.0.0")
        .with_network(reseau)
        .with_network_aliases("consul")
        .with_exposed_ports(8500)
    )
    with consul:
        url = url_depuis_hote(consul, 8500)
        _attendre_leader(url)
        yield url


@pytest.fixture(scope="session")
def url_hote() -> Callable[[DockerContainer, int], str]:
    """Donne accès à url_depuis_hote aux tests qui démarrent leurs propres conteneurs."""
    return url_depuis_hote


@pytest.fixture
def origine_front() -> str:
    """Origine autorisée par CORS dans la gateway de test."""
    return ORIGINE_FRONT


@pytest.fixture(scope="module")
def secrets_realm() -> dict[str, str]:
    """Valeurs des variables ${...} du realm, tirées au hasard pour chaque module de tests."""
    return {
        "KEYCLOAK_SERVICES_SECRET": secrets.token_urlsafe(24),
        "KEYCLOAK_MDP_CLIENT": secrets.token_urlsafe(16),
        "KEYCLOAK_MDP_PARTENAIRE": secrets.token_urlsafe(16),
        "KEYCLOAK_MDP_ADMIN": secrets.token_urlsafe(16),
        "KEYCLOAK_URL_FRONT": "http://localhost",
    }


@pytest.fixture(scope="module")
def valeurs_env_prod() -> dict[str, str]:
    """Fichier d'environnement de démo synthétique : jamais de Neon, jamais le vrai domaine."""
    return {
        "DOMAINE": DOMAINE_DEMO,
        "IMAGE_TAG": "sha-0000000",
        "ECHO_DATABASE_URL": (
            f"postgresql+asyncpg://echo:{secrets.token_urlsafe(16)}@base.exemple.test:5432/echo"
        ),
        "KEYCLOAK_DB_URL": "jdbc:postgresql://base.exemple.test:5432/keycloak?sslmode=require",
        "KEYCLOAK_DB_USERNAME": "keycloak",
        "KEYCLOAK_DB_PASSWORD": secrets.token_urlsafe(16),
        "KEYCLOAK_URL_FRONT": f"https://{DOMAINE_DEMO}",
        "KEYCLOAK_ADMIN": "admin.demo",
        "KEYCLOAK_ADMIN_PASSWORD": secrets.token_urlsafe(16),
        "KEYCLOAK_REALM": "billetterie",
        "KEYCLOAK_SERVICES_SECRET": secrets.token_urlsafe(24),
        "KEYCLOAK_MDP_CLIENT": secrets.token_urlsafe(16),
        "KEYCLOAK_MDP_PARTENAIRE": secrets.token_urlsafe(16),
        "KEYCLOAK_MDP_ADMIN": secrets.token_urlsafe(16),
        "RABBITMQ_DEFAULT_USER": "billetterie",
        "RABBITMQ_DEFAULT_PASS": secrets.token_urlsafe(16),
        "ACME_EMAIL": "acme.test@exemple.test",
        # Autorité injoignable : Traefik garde son certificat par défaut dans les tests.
        "ACME_CA_SERVER": "https://acme.exemple.test/directory",
        "CORS_ORIGINS": f"https://{DOMAINE_DEMO}",
        "ROUTES_PUBLIQUES": "",
        "TRAEFIK_POINT_ENTREE": "websecure",
    }


@pytest.fixture(scope="module")
def compose_prod(
    tmp_path_factory: pytest.TempPathFactory, valeurs_env_prod: dict[str, str]
) -> ExecuterComposeProd:
    """Lance `docker compose -f compose.prod.yaml --env-file <fichier> config <options>`.

    Le fichier d'environnement est écrit dans un dossier temporaire ; les variables du poste
    qui portent le même nom sont retirées, seul le fichier fait foi.
    """
    dossier = tmp_path_factory.mktemp("env-prod")

    def executer(valeurs: dict[str, str], options: list[str]) -> subprocess.CompletedProcess[str]:
        fichier = dossier / f"env-{secrets.token_hex(4)}"
        fichier.write_text("".join(f"{nom}={valeur}\n" for nom, valeur in valeurs.items()))
        environnement = {
            nom: valeur for nom, valeur in os.environ.items() if nom not in valeurs_env_prod
        }
        return subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_PROD), "--env-file", str(fichier), "config"]
            + options,
            cwd=RACINE,
            env=environnement,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )

    return executer


@pytest.fixture(scope="module")
def config_prod(compose_prod: ExecuterComposeProd, valeurs_env_prod: dict[str, str]) -> Any:
    """Configuration de prod résolue par Compose (ancres, interpolation, mémoire en octets)."""
    resultat = compose_prod(valeurs_env_prod, ["--format", "json"])
    if resultat.returncode != 0:
        pytest.fail(f"docker compose config a échoué : {resultat.stderr}")
    return json.loads(resultat.stdout)


@pytest.fixture(scope="module")
def valeurs_env_locale() -> dict[str, str]:
    """Fichier .env local synthétique : chaque mot de passe et secret est tiré au hasard."""
    valeurs = {
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": secrets.token_urlsafe(16),
        "ECHO_DB_PASSWORD": secrets.token_urlsafe(16),
        "KEYCLOAK_DB_PASSWORD": secrets.token_urlsafe(16),
        "RABBITMQ_DEFAULT_USER": "billetterie",
        "RABBITMQ_DEFAULT_PASS": secrets.token_urlsafe(16),
        "KEYCLOAK_ADMIN": "admin.test",
        "KEYCLOAK_ADMIN_PASSWORD": secrets.token_urlsafe(16),
        "KEYCLOAK_REALM": "billetterie",
        "KEYCLOAK_SERVICES_SECRET": secrets.token_urlsafe(24),
        "KEYCLOAK_MDP_CLIENT": secrets.token_urlsafe(16),
        "KEYCLOAK_MDP_PARTENAIRE": secrets.token_urlsafe(16),
        "KEYCLOAK_MDP_ADMIN": secrets.token_urlsafe(16),
        "KEYCLOAK_URL_FRONT": "http://localhost",
        "CORS_ORIGINS": "http://localhost",
        "ROUTES_PUBLIQUES": "",
        "GRAFANA_ADMIN_PASSWORD": secrets.token_urlsafe(16),
    }
    for service in SERVICES:
        valeurs[service.variable_mot_de_passe] = secrets.token_urlsafe(16)
    return valeurs


@pytest.fixture(scope="module")
def compose_local(
    tmp_path_factory: pytest.TempPathFactory, valeurs_env_locale: dict[str, str]
) -> Callable[[list[str]], subprocess.CompletedProcess[str]]:
    """Lance `docker compose -f compose.yaml --env-file <fichier de test> config <options>`.

    Les variables du poste de même nom sont retirées : seul le fichier de test fait foi.
    """
    fichier = tmp_path_factory.mktemp("env-local") / "env"
    fichier.write_text("".join(f"{nom}={valeur}\n" for nom, valeur in valeurs_env_locale.items()))
    environnement = {
        nom: valeur for nom, valeur in os.environ.items() if nom not in valeurs_env_locale
    }

    def executer(options: list[str]) -> subprocess.CompletedProcess[str]:
        commande = [
            "docker", "compose", "-f", str(COMPOSE_LOCAL), "--env-file", str(fichier), "config"
        ] + options  # fmt: skip
        try:
            return subprocess.run(
                commande,
                cwd=RACINE,
                env=environnement,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=DELAI_ETAPE,
                check=False,
            )
        except subprocess.TimeoutExpired as depasse:
            raise AssertionError(
                f"docker compose config {' '.join(options)} : échéance de {DELAI_ETAPE:.0f} s "
                f"dépassée ; dernière sortie d'erreur : {depasse.stderr!r}"
            ) from None

    return executer


@pytest.fixture(scope="module")
def config_locale(compose_local: Callable[[list[str]], subprocess.CompletedProcess[str]]) -> Any:
    """Configuration locale résolue par Compose (ancres et interpolation appliquées)."""
    resultat = compose_local(["--format", "json"])
    if resultat.returncode != 0:
        pytest.fail(f"docker compose config a échoué : {resultat.stderr}")
    return json.loads(resultat.stdout)


@pytest.fixture(scope="module")
def verificateur(reseau: Network) -> Iterator[None]:
    """Faux vérificateur qui accepte tout (whoami répond 200 à toute requête).

    Les tests de la gateway portent sur le routage, pas sur les jetons ; ceux du vrai
    vérificateur (test_verification_jeton.py) redéfinissent cette fixture.
    """
    with (
        DockerContainer(IMAGE_WHOAMI)
        .with_command("--port 8000 --name verificateur")
        .with_network(reseau)
        .with_network_aliases("verificateur")
    ):
        yield


@pytest.fixture(scope="module")
def gateway_url(reseau: Network, consul_url: str, verificateur: None) -> Iterator[str]:
    """Démarre Traefik avec la configuration réelle de infra/traefik/."""
    traefik = (
        DockerContainer(IMAGE_TRAEFIK)
        .with_env("CORS_ORIGINS", ORIGINE_FRONT)
        .with_volume_mapping(str(DOSSIER_TRAEFIK / "traefik.yml"), "/etc/traefik/traefik.yml")
        .with_volume_mapping(str(DOSSIER_TRAEFIK / "dynamique.yml"), "/etc/traefik/dynamique.yml")
        .with_volume_mapping(str(DOSSIER_TRAEFIK / "plugins-local"), "/plugins-local")
        .with_network(reseau)
        .with_exposed_ports(80, 8080)
    )
    with traefik:
        _attendre_ping(url_depuis_hote(traefik, 8080))
        yield url_depuis_hote(traefik, 80)


@pytest.fixture
def instances_whoami(reseau: Network) -> Iterator[list[str]]:
    """Deux instances d'un même service, qui renvoient leur nom et les en-têtes reçus."""
    noms = ["instance-a", "instance-b"]
    conteneurs = [
        DockerContainer(IMAGE_WHOAMI)
        .with_command(f"--name {nom}")
        .with_network(reseau)
        .with_network_aliases(nom)
        for nom in noms
    ]
    for conteneur in conteneurs:
        conteneur.start()
    try:
        yield noms
    finally:
        for conteneur in conteneurs:
            conteneur.stop()


@pytest.fixture
def faux_service(reseau: Network) -> Iterator[DockerContainer]:
    """Serveur HTTP qui répond 200 sur toutes les routes, /health compris."""
    conteneur = (
        DockerContainer(IMAGE_FAUX_SERVICE)
        .with_command("-listen=:5678 -text=ok")
        .with_network(reseau)
        .with_network_aliases("faux-service")
    )
    with conteneur:
        yield conteneur


def _attendre_leader(url: str, delai: float = 30.0) -> None:
    limite = time.monotonic() + delai
    while time.monotonic() < limite:
        try:
            if httpx.get(f"{url}/v1/status/leader", timeout=2.0).json():
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise TimeoutError("Consul n'a pas élu de leader à temps")


def _attendre_ping(url: str, delai: float = 30.0) -> None:
    limite = time.monotonic() + delai
    while time.monotonic() < limite:
        try:
            if httpx.get(f"{url}/ping", timeout=2.0).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise TimeoutError("Traefik n'a pas démarré à temps")
