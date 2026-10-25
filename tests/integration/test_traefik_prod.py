"""Traefik de démo (BIL-F29) : configuration de prod réelle, redirection HTTP vers HTTPS.

Traefik reçoit exactement les montages, l'environnement et la commande du service traefik de
compose.prod.yaml (résolus par config_prod) ; Consul vient du conftest. L'autorité ACME du
fichier d'environnement de test est injoignable : Traefik sert son certificat par défaut, la
vérification TLS est donc coupée côté client.
"""

import time
from collections.abc import Iterator
from typing import Any

import anyio
import httpx
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network

from commun.registre import desenregistrer, enregistrer, tags_traefik

pytestmark = pytest.mark.anyio

IMAGE_TRAEFIK = "traefik:v3.5.3"
IMAGE_WHOAMI = "traefik/whoami:v1.11.0"
DOMAINE = "demo.exemple.test"
ROUTE = "/api/v1/echos/bonjour"
NOM_WHOAMI = "whoami-prod"


@pytest.fixture(autouse=True)
def variable_consul(consul_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONSUL_URL", consul_url)


@pytest.fixture(scope="module")
def traefik_prod(config_prod: Any, reseau: Network, consul_url: str) -> Iterator[dict[str, str]]:
    """Traefik lancé comme le service traefik de compose.prod.yaml ; URL HTTP et HTTPS."""
    service = config_prod["services"]["traefik"]
    traefik = DockerContainer(service.get("image", IMAGE_TRAEFIK))
    for volume in service.get("volumes", []):
        if volume.get("type") == "bind":
            traefik = traefik.with_volume_mapping(volume["source"], volume["target"])
    for nom, valeur in (service.get("environment") or {}).items():
        traefik = traefik.with_env(nom, valeur or "")
    if service.get("command"):
        traefik = traefik.with_command(service["command"])
    traefik = traefik.with_network(reseau).with_exposed_ports(80, 443)
    with traefik:
        hote = traefik.get_container_host_ip().replace("localhost", "127.0.0.1")
        yield {
            "http": f"http://{hote}:{traefik.get_exposed_port(80)}",
            "https": f"https://{hote}:{traefik.get_exposed_port(443)}",
        }


@pytest.fixture
def whoami(reseau: Network) -> Iterator[str]:
    """Faux service echo : répond 200 à toute requête avec son nom."""
    with (
        DockerContainer(IMAGE_WHOAMI)
        .with_command(f"--name {NOM_WHOAMI}")
        .with_network(reseau)
        .with_network_aliases(NOM_WHOAMI)
    ):
        yield NOM_WHOAMI


async def _appel(client: httpx.AsyncClient, url: str) -> httpx.Response | str:
    """Réponse, ou description de l'erreur réseau (point d'entrée absent, TLS refusé)."""
    try:
        return await client.get(url, headers={"Host": DOMAINE})
    except httpx.HTTPError as erreur:
        return f"{type(erreur).__name__}: {erreur}"


async def _attendre(
    client: httpx.AsyncClient, url: str, statuts: set[int], delai: float = 45.0
) -> httpx.Response | str:
    """Dernière réponse obtenue, dès que son statut est attendu ou au bout du délai."""
    limite = time.monotonic() + delai
    resultat: httpx.Response | str = "aucun appel"
    while time.monotonic() < limite:
        resultat = await _appel(client, url)
        if isinstance(resultat, httpx.Response) and resultat.status_code in statuts:
            return resultat
        await anyio.sleep(1)
    return resultat


async def test_traefik_de_prod_redirige_http_vers_https_et_route_l_api(
    traefik_prod: dict[str, str], whoami: str
) -> None:
    tags = tags_traefik("echo", "echos", middlewares="public@file", point_entree="websecure")
    identifiant = await enregistrer("echo", whoami, 80, tags)
    try:
        async with httpx.AsyncClient(verify=False, follow_redirects=False, timeout=5.0) as client:
            redirection = await _attendre(client, f"{traefik_prod['http']}{ROUTE}", {301, 308})
            assert isinstance(redirection, httpx.Response), redirection
            assert redirection.status_code in {301, 308}, redirection.status_code
            assert redirection.headers.get("location") == f"https://{DOMAINE}{ROUTE}"

            reponse = await _attendre(client, f"{traefik_prod['https']}{ROUTE}", {200})
            assert isinstance(reponse, httpx.Response), reponse
            assert reponse.status_code == 200, reponse.status_code
            assert f"Name: {whoami}" in reponse.text
    finally:
        await desenregistrer(identifiant)
