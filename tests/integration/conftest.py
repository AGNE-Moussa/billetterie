"""Conteneurs partagés par les tests d'intégration."""

import time
from collections.abc import Iterator

import httpx
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network

IMAGE_CONSUL = "hashicorp/consul:1.21.5"
IMAGE_FAUX_SERVICE = "hashicorp/http-echo:1.0"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


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
        hote = consul.get_container_host_ip()
        # Sous Windows, « localhost » passe d'abord par IPv6 (::1) et Docker Desktop coupe
        # alors les connexions après la première requête : on force IPv4.
        if hote == "localhost":
            hote = "127.0.0.1"
        url = f"http://{hote}:{consul.get_exposed_port(8500)}"
        _attendre_leader(url)
        yield url


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
