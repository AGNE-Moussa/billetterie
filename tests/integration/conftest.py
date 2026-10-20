"""Conteneurs partagés par les tests d'intégration."""

import secrets
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network

IMAGE_CONSUL = "hashicorp/consul:1.21.5"
IMAGE_FAUX_SERVICE = "hashicorp/http-echo:1.0"
IMAGE_TRAEFIK = "traefik:v3.5.3"
IMAGE_WHOAMI = "traefik/whoami:v1.11.0"
DOSSIER_TRAEFIK = Path(__file__).resolve().parents[2] / "infra" / "traefik"
ORIGINE_FRONT = "http://localhost:5173"


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
    }


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
