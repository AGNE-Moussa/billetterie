"""Démo publique (BIL-F29) : HTTPS, redirection, front, Keycloak et CORS sur le vrai domaine.

Joués à la main depuis le poste, jamais par la CI : `DEMO_URL=https://<domaine>` dans
l'environnement, puis `uv run pytest tests/smoke/test_demo.py -m smoke`. Requêtes sans jeton
uniquement : rien n'atteint la base Neon (le vérificateur répond 401 avant tout service).
"""

import os
import socket
from urllib.parse import urlparse

import httpx
import pytest

pytestmark = pytest.mark.smoke

ROUTE_ECHO = "/api/v1/echos/bonjour"
PORTS_FERMES = (8080, 5672, 8500, 15672, 5432)


@pytest.fixture(scope="module")
def demo_url() -> str:
    """URL publique de la démo, sans barre finale ; test ignoré si elle est absente."""
    url = os.environ.get("DEMO_URL", "").rstrip("/")
    if not url:
        pytest.skip("DEMO_URL absente : définir DEMO_URL=https://<domaine> pour viser la démo")
    if urlparse(url).scheme != "https":
        pytest.fail(f"DEMO_URL doit commencer par https:// : {url}")
    try:
        socket.create_connection((_domaine(url), 443), timeout=5.0).close()
    except OSError:
        pytest.skip(f"La démo ne répond pas sur le port 443 : {url}")
    return url


def _domaine(url: str) -> str:
    return urlparse(url).hostname or ""


def test_l_api_de_la_demo_repond_en_https_avec_un_certificat_valide(demo_url: str) -> None:
    # Vérification TLS active (défaut de httpx) : un certificat invalide lève une erreur.
    reponse = httpx.get(f"{demo_url}{ROUTE_ECHO}", timeout=10.0)

    assert reponse.status_code == 401
    assert reponse.headers["content-type"].startswith("application/problem+json")
    assert reponse.headers.get("www-authenticate", "").startswith("Bearer")


def test_la_demo_redirige_http_vers_https(demo_url: str) -> None:
    domaine = _domaine(demo_url)

    reponse = httpx.get(f"http://{domaine}{ROUTE_ECHO}", follow_redirects=False, timeout=10.0)

    assert reponse.status_code in {301, 308}
    assert reponse.headers["location"] == f"https://{domaine}{ROUTE_ECHO}"


@pytest.mark.parametrize("port", PORTS_FERMES)
def test_la_demo_n_expose_ni_le_tableau_de_bord_ni_d_autre_port(demo_url: str, port: int) -> None:
    try:
        socket.create_connection((_domaine(demo_url), port), timeout=3.0).close()
    except OSError:
        return
    pytest.fail(f"Le port {port} de la démo accepte les connexions")


def test_la_racine_de_la_demo_sert_le_front(demo_url: str) -> None:
    reponse = httpx.get(f"{demo_url}/", timeout=10.0)

    assert reponse.status_code == 200
    assert reponse.headers["content-type"].startswith("text/html")
    assert 'id="root"' in reponse.text


def test_le_keycloak_de_la_demo_annonce_l_emetteur_du_domaine(demo_url: str) -> None:
    reponse = httpx.get(
        f"{demo_url}/auth/realms/billetterie/.well-known/openid-configuration", timeout=10.0
    )

    assert reponse.status_code == 200
    configuration = reponse.json()
    assert configuration["issuer"] == f"{demo_url}/auth/realms/billetterie"
    assert configuration["authorization_endpoint"].startswith(f"{demo_url}/auth/")


def test_la_demo_n_autorise_aucune_origine_etrangere(demo_url: str) -> None:
    etrangere = "https://autre.exemple.test"

    reponse = httpx.options(
        f"{demo_url}/api/v1/echos",
        headers={"Origin": etrangere, "Access-Control-Request-Method": "GET"},
        timeout=10.0,
    )

    assert reponse.headers.get("access-control-allow-origin") != etrangere
