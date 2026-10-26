"""Keycloak de démo (BIL-F29) : mode production derrière le proxy, realm paramétré.

Keycloak reçoit la commande, l'environnement et les montages du service keycloak de
compose.prod.yaml (résolus par config_prod) ; seule la base change : PostgreSQL 16 jetable
(Testcontainers), jamais Neon.
"""

import base64
import hashlib
import secrets
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network

DOMAINE = "demo.exemple.test"
EMETTEUR = f"https://{DOMAINE}/auth/realms/billetterie"
CONFIGURATION_OIDC = "/auth/realms/billetterie/.well-known/openid-configuration"
AUTORISATION = "/auth/realms/billetterie/protocol/openid-connect/auth"
EN_TETES_PROXY = {"X-Forwarded-Proto": "https", "X-Forwarded-Host": DOMAINE}
DELAI_DEMARRAGE = 240.0


@dataclass
class KeycloakDemarre:
    """URL de Keycloak vue depuis l'hôte, ou None avec la raison de l'échec du démarrage."""

    url: str | None
    raison: str = ""


def _attendre_configuration(url: str, conteneur: DockerContainer) -> str:
    """Attend la configuration OpenID du realm ; renvoie une raison vide si elle répond."""
    limite = time.monotonic() + DELAI_DEMARRAGE
    while time.monotonic() < limite:
        try:
            reponse = httpx.get(f"{url}{CONFIGURATION_OIDC}", headers=EN_TETES_PROXY, timeout=3.0)
            if reponse.status_code == 200:
                return ""
        except httpx.HTTPError:
            pass
        conteneur.get_wrapped_container().reload()
        if conteneur.get_wrapped_container().status == "exited":
            break
        time.sleep(2)
    sortie, erreurs = conteneur.get_logs()
    return "Keycloak n'a pas démarré : " + (sortie + erreurs).decode(errors="replace")[-2000:]


@pytest.fixture(scope="module")
def keycloak_prod(config_prod: Any, reseau: Network) -> Iterator[KeycloakDemarre]:
    service = config_prod["services"].get("keycloak")
    if service is None:
        yield KeycloakDemarre(None, "Aucun service keycloak dans compose.prod.yaml")
        return
    mot_de_passe = secrets.token_urlsafe(16)
    base = (
        PostgresContainer(
            "postgres:16.10-alpine", username="keycloak", password=mot_de_passe, dbname="keycloak"
        )
        .with_network(reseau)
        .with_network_aliases("base-keycloak")
    )
    with base:
        environnement = dict(service.get("environment") or {})
        environnement |= {
            "KC_DB_URL": "jdbc:postgresql://base-keycloak:5432/keycloak",
            "KC_DB_USERNAME": "keycloak",
            "KC_DB_PASSWORD": mot_de_passe,
        }
        keycloak = DockerContainer(service["image"]).with_network(reseau).with_exposed_ports(8080)
        for nom, valeur in environnement.items():
            keycloak = keycloak.with_env(nom, valeur or "")
        for volume in service.get("volumes", []):
            if volume.get("type") == "bind":
                keycloak = keycloak.with_volume_mapping(volume["source"], volume["target"])
        if service.get("command"):
            keycloak = keycloak.with_command(service["command"])
        with keycloak:
            hote = keycloak.get_container_host_ip().replace("localhost", "127.0.0.1")
            url = f"http://{hote}:{keycloak.get_exposed_port(8080)}"
            raison = _attendre_configuration(url, keycloak)
            yield KeycloakDemarre(None if raison else url, raison)


def _parametres_autorisation(redirection: str) -> dict[str, str]:
    verificateur = secrets.token_urlsafe(48)
    defi = base64.urlsafe_b64encode(hashlib.sha256(verificateur.encode()).digest()).rstrip(b"=")
    return {
        "client_id": "frontend",
        "redirect_uri": redirection,
        "response_type": "code",
        "code_challenge": defi.decode(),
        "code_challenge_method": "S256",
    }


def test_keycloak_en_mode_production_derriere_le_proxy_annonce_l_emetteur_https(
    keycloak_prod: KeycloakDemarre,
) -> None:
    assert keycloak_prod.url, keycloak_prod.raison

    reponse = httpx.get(f"{keycloak_prod.url}{CONFIGURATION_OIDC}", headers=EN_TETES_PROXY)

    assert reponse.status_code == 200
    assert reponse.json()["issuer"] == EMETTEUR


def test_keycloak_de_prod_refuse_une_redirection_hors_du_domaine(
    keycloak_prod: KeycloakDemarre,
) -> None:
    assert keycloak_prod.url, keycloak_prod.raison

    with httpx.Client(base_url=keycloak_prod.url, headers=EN_TETES_PROXY, timeout=10.0) as client:
        etrangere = client.get(
            AUTORISATION, params=_parametres_autorisation("https://autre.exemple.test/")
        )
        du_domaine = client.get(
            AUTORISATION, params=_parametres_autorisation(f"https://{DOMAINE}/")
        )

    assert etrangere.status_code == 400
    assert "Invalid parameter: redirect_uri" in etrangere.text
    assert du_domaine.status_code == 200, du_domaine.text[:300]
    assert 'id="kc-form-login"' in du_domaine.text
