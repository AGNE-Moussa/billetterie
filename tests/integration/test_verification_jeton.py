"""Gateway et vrai vérificateur de bout en bout : Traefik, infra/verificateur, Keycloak, whoami.

Les jetons viennent d'un Keycloak qui importe le realm versionné ; le vérificateur lit ses clés
par le réseau Docker, comme dans le compose. Le jeton expiré (CA3) est couvert par les tests
unitaires du vérificateur : Keycloak ne délivre pas de jeton déjà expiré.
"""

import re
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import anyio
import httpx
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.image import DockerImage
from testcontainers.core.network import Network

from commun.registre import desenregistrer, enregistrer, tags_traefik

pytestmark = pytest.mark.anyio

RACINE = Path(__file__).resolve().parents[2]
IMAGE_KEYCLOAK = "quay.io/keycloak/keycloak:26.4.1"
EMETTEUR = "http://localhost/auth/realms/billetterie"
CERTS = "http://keycloak:8080/auth/realms/billetterie/protocol/openid-connect/certs"
PORT_WHOAMI = 80


def _attendre(url: str, delai: float = 180.0) -> None:
    limite = time.monotonic() + delai
    while time.monotonic() < limite:
        try:
            if httpx.get(url, timeout=2.0).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise TimeoutError(f"{url} ne répond pas à temps")


@pytest.fixture(scope="module")
def keycloak_url(
    reseau: Network,
    secrets_realm: dict[str, str],
    url_hote: Callable[[DockerContainer, int], str],
) -> Iterator[str]:
    """Keycloak sur le réseau de la gateway, émetteur fixe comme dans le compose."""
    keycloak = (
        DockerContainer(IMAGE_KEYCLOAK)
        .with_command("start-dev --import-realm")
        .with_env("KC_HTTP_RELATIVE_PATH", "/auth")
        .with_env("KC_HOSTNAME", "http://localhost/auth")
        .with_env("KC_HOSTNAME_BACKCHANNEL_DYNAMIC", "true")
        .with_env("KC_HEALTH_ENABLED", "true")
        .with_volume_mapping(str(RACINE / "infra" / "keycloak"), "/opt/keycloak/data/import")
        .with_network(reseau)
        .with_network_aliases("keycloak")
        .with_exposed_ports(8080, 9000)
    )
    for nom, valeur in secrets_realm.items():
        keycloak = keycloak.with_env(nom, valeur)
    with keycloak:
        _attendre(f"{url_hote(keycloak, 9000)}/auth/health/ready")
        yield url_hote(keycloak, 8080)


@pytest.fixture(scope="module")
def verificateur(
    reseau: Network, keycloak_url: str, url_hote: Callable[[DockerContainer, int], str]
) -> Iterator[None]:
    """Remplace le faux vérificateur du conftest par l'image construite depuis le dépôt."""
    with DockerImage(
        path=str(RACINE),
        dockerfile_path="infra/verificateur/Dockerfile",
        tag="billetterie/verificateur:test",
    ) as image:
        conteneur = (
            DockerContainer(str(image))
            .with_env("JWT_EMETTEUR", EMETTEUR)
            .with_env("JWKS_URL", CERTS)
            .with_env("ROUTES_PUBLIQUES", "GET /api/v1/vitrines")
            .with_network(reseau)
            .with_network_aliases("verificateur")
            .with_exposed_ports(8000)
        )
        with conteneur:
            _attendre(f"{url_hote(conteneur, 8000)}/health", delai=60.0)
            yield


@pytest.fixture(autouse=True)
def variable_consul(consul_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONSUL_URL", consul_url)


@pytest.fixture
def jeton_services(keycloak_url: str, secrets_realm: dict[str, str]) -> str:
    reponse = httpx.post(
        f"{keycloak_url}/auth/realms/billetterie/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "services",
            "client_secret": secrets_realm["KEYCLOAK_SERVICES_SECRET"],
        },
    )
    reponse.raise_for_status()
    jeton: str = reponse.json()["access_token"]
    return jeton


async def _exposer(service: str, instances: list[str]) -> list[str]:
    tags = tags_traefik(service, service)
    return [await enregistrer(service, nom, PORT_WHOAMI, tags) for nom in instances]


async def _attendre_route(
    client: httpx.AsyncClient, route: str, entetes: dict[str, str], delai: float = 45.0
) -> None:
    """Attend que Traefik ait découvert la route (404 tant qu'elle n'existe pas)."""
    limite = time.monotonic() + delai
    while time.monotonic() < limite:
        if (await client.get(route, headers=entetes)).status_code != 404:
            return
        await anyio.sleep(1)
    raise AssertionError(f"Route {route} jamais découverte par Traefik")


def _entete_recu(reponse: httpx.Response, nom: str) -> str | None:
    """Valeur d'un en-tête reçu par le service (whoami les recopie dans sa réponse)."""
    trouve = re.search(rf"^{nom}: (.*)$", reponse.text, re.MULTILINE | re.IGNORECASE)
    return trouve.group(1).strip() if trouve else None


async def test_route_protegee_sans_jeton_puis_avec_jeton_valide(
    gateway_url: str, instances_whoami: list[str], jeton_services: str
) -> None:
    identifiants = await _exposer("protegees", instances_whoami)
    route = "/api/v1/protegees"
    bearer = {"Authorization": f"Bearer {jeton_services}"}
    async with httpx.AsyncClient(base_url=gateway_url) as client:
        await _attendre_route(client, route, bearer)

        # CA1 : 401 renvoyé par le vérificateur, le service n'est pas appelé.
        sans_jeton = await client.get(route)
        assert sans_jeton.status_code == 401
        assert sans_jeton.headers["content-type"] == "application/problem+json"
        assert sans_jeton.json()["code"] == "JETON_ABSENT"
        assert _entete_recu(sans_jeton, "Name") is None

        # CA2 : le service reçoit l'identité extraite du jeton.
        avec_jeton = await client.get(route, headers=bearer)
        assert avec_jeton.status_code == 200
        assert _entete_recu(avec_jeton, "Name") in instances_whoami
        assert _entete_recu(avec_jeton, "X-User-Id")
        assert _entete_recu(avec_jeton, "X-Client-Id") == "services"

        # Un jeton modifié (signature cassée) est refusé.
        entete, contenu, _signature = jeton_services.split(".")
        falsifie = {"Authorization": f"Bearer {entete}.{contenu}.c2lnbmF0dXJl"}
        refuse = await client.get(route, headers=falsifie)
        assert refuse.status_code == 401
        assert refuse.json()["code"] == "JETON_INVALIDE"

    for identifiant in identifiants:
        await desenregistrer(identifiant)


async def test_une_identite_fournie_par_le_client_n_atteint_pas_le_service(
    gateway_url: str, instances_whoami: list[str]
) -> None:
    identifiants = await _exposer("vitrines", instances_whoami)
    route = "/api/v1/vitrines"
    async with httpx.AsyncClient(base_url=gateway_url) as client:
        await _attendre_route(client, route, {})

        # Route publique : passe sans jeton, mais le faux X-User-Id est retiré par Traefik.
        reponse = await client.get(route, headers={"X-User-Id": "admin-usurpe"})
        assert reponse.status_code == 200
        assert _entete_recu(reponse, "X-User-Id") is None

        # Une autre méthode sur la même route reste protégée.
        assert (await client.post(route)).status_code == 401

    for identifiant in identifiants:
        await desenregistrer(identifiant)


async def test_le_preflight_cors_passe_sans_jeton(
    gateway_url: str, instances_whoami: list[str], jeton_services: str, origine_front: str
) -> None:
    identifiants = await _exposer("preflight", instances_whoami)
    route = "/api/v1/preflight"
    async with httpx.AsyncClient(base_url=gateway_url) as client:
        await _attendre_route(client, route, {"Authorization": f"Bearer {jeton_services}"})

        reponse = await client.options(
            route,
            headers={
                "Origin": origine_front,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization",
            },
        )

        assert reponse.status_code == 200
        assert reponse.headers["Access-Control-Allow-Origin"] == origine_front

    for identifiant in identifiants:
        await desenregistrer(identifiant)
