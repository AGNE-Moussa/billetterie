"""Plateforme locale (BIL-001) : les cinq services métier sont sains dans Consul et via Traefik.

Joués contre `make up` (et `make observabilite` pour Prometheus) par `make test-smoke`, jamais
par la CI. Chaque test est ignoré si le composant qu'il interroge ne répond pas. Le jeton du
client `services` est demandé à Keycloak avec le secret lu dans `.env`, jamais écrit ici.
"""

from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.smoke

GATEWAY = "http://localhost"
CONSUL = "http://127.0.0.1:8500"
PROMETHEUS = "http://127.0.0.1:9090"
RACINE = Path(__file__).resolve().parents[2]

# (service, ressource du préfixe, nombre d'instances)
SERVICES = [
    ("catalogue", "events", 1),
    ("billets", "seats", 2),
    ("commandes", "orders", 2),
    ("paiements", "payments", 1),
    ("notifications", "notifications", 1),
]
IDS = [service for service, _, _ in SERVICES]


def _lire_env() -> dict[str, str]:
    fichier = RACINE / ".env"
    if not fichier.exists():
        return {}
    valeurs: dict[str, str] = {}
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        nom, valeur = ligne.split("=", 1)
        valeurs[nom.strip()] = valeur.strip().strip("'\"")
    return valeurs


def _repond(url: str) -> bool:
    try:
        httpx.get(url, timeout=3.0)
    except httpx.HTTPError:
        return False
    return True


@pytest.fixture(scope="module")
def consul() -> str:
    if not _repond(f"{CONSUL}/v1/status/leader"):
        pytest.skip(f"Consul ne répond pas sur {CONSUL} : lancer make up")
    return CONSUL


@pytest.fixture(scope="module")
def gateway() -> str:
    if not _repond(f"{GATEWAY}/"):
        pytest.skip(f"La gateway ne répond pas sur {GATEWAY} : lancer make up")
    return GATEWAY


@pytest.fixture(scope="module")
def jeton(gateway: str) -> str:
    env = _lire_env()
    secret = env.get("KEYCLOAK_SERVICES_SECRET")
    if not secret:
        pytest.skip("KEYCLOAK_SERVICES_SECRET absent de .env")
    realm = env.get("KEYCLOAK_REALM") or "billetterie"
    reponse = httpx.post(
        f"{gateway}/auth/realms/{realm}/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "services",
            "client_secret": secret,
        },
        timeout=10.0,
    )
    assert reponse.status_code == 200, "Keycloak refuse le client services"
    return str(reponse.json()["access_token"])


@pytest.mark.parametrize(("service", "ressource", "instances"), SERVICES, ids=IDS)
def test_les_cinq_services_sont_verts_dans_consul(
    consul: str, service: str, ressource: str, instances: int
) -> None:
    reponse = httpx.get(f"{consul}/v1/health/service/{service}", timeout=5.0)

    assert reponse.status_code == 200
    entrees = reponse.json()
    assert len(entrees) == instances, f"{service} : {len(entrees)} instance(s) inscrite(s)"
    for entree in entrees:
        statuts = {check["Status"] for check in entree["Checks"]}
        assert statuts == {"passing"}, f"{entree['Service']['ID']} : {statuts}"


@pytest.mark.parametrize(("service", "ressource", "instances"), SERVICES, ids=IDS)
def test_la_sante_de_chaque_service_repond_via_traefik(
    gateway: str, jeton: str, service: str, ressource: str, instances: int
) -> None:
    reponse = httpx.get(
        f"{gateway}/api/v1/{ressource}/health",
        headers={"Authorization": f"Bearer {jeton}"},
        timeout=10.0,
    )

    assert reponse.status_code == 200, f"{service} : {reponse.status_code}"
    assert reponse.headers["content-type"].startswith("application/json")
    assert reponse.json() == {"statut": "ok"}
    assert reponse.headers.get("x-correlation-id")


@pytest.mark.parametrize(("service", "ressource", "instances"), SERVICES, ids=IDS)
def test_sans_jeton_la_sante_via_traefik_est_refusee(
    gateway: str, service: str, ressource: str, instances: int
) -> None:
    reponse = httpx.get(f"{gateway}/api/v1/{ressource}/health", timeout=10.0)

    assert reponse.status_code == 401, f"{service} : {reponse.status_code}"
    assert reponse.headers["content-type"].startswith("application/problem+json")
    assert reponse.headers.get("www-authenticate", "").startswith("Bearer")


def test_prometheus_mesure_chaque_instance_des_cinq_services() -> None:
    if not _repond(f"{PROMETHEUS}/-/ready"):
        pytest.skip(f"Prometheus ne répond pas sur {PROMETHEUS} : lancer make observabilite")

    reponse = httpx.get(
        f"{PROMETHEUS}/api/v1/query", params={"query": 'up{job="services"}'}, timeout=10.0
    )

    assert reponse.status_code == 200
    series = reponse.json()["data"]["result"]
    for service, _, instances in SERVICES:
        vivantes = [
            s for s in series if s["metric"].get("service") == service and s["value"][1] == "1"
        ]
        assert len(vivantes) == instances, f"{service} : {len(vivantes)} instance(s) mesurée(s)"
