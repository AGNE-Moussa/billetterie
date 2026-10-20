"""Realm Keycloak « billetterie » importé depuis infra/keycloak/realm-billetterie.json.

Client Credentials pour le client services, Authorization Code + PKCE pour le client frontend,
rôles dans les jetons, durée de vie de 5 minutes.
"""

import base64
import hashlib
import html
import json
import re
import secrets
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from testcontainers.core.container import DockerContainer

IMAGE_KEYCLOAK = "quay.io/keycloak/keycloak:26.4.1"
DOSSIER_REALM = Path(__file__).resolve().parents[2] / "infra" / "keycloak"
REALM = "/auth/realms/billetterie/protocol/openid-connect"
REDIRECTION = "http://localhost/rappel"
ROLES_METIER = {"customer", "partner", "admin"}


@pytest.fixture(scope="module")
def keycloak_url(
    secrets_realm: dict[str, str], url_hote: Callable[[DockerContainer, int], str]
) -> Iterator[str]:
    """Keycloak en mode dev (base H2 interne), realm importé au démarrage."""
    keycloak = (
        DockerContainer(IMAGE_KEYCLOAK)
        .with_command("start-dev --import-realm")
        .with_env("KC_HTTP_RELATIVE_PATH", "/auth")
        .with_env("KC_HEALTH_ENABLED", "true")
        .with_volume_mapping(str(DOSSIER_REALM), "/opt/keycloak/data/import")
        .with_exposed_ports(8080, 9000)
    )
    for nom, valeur in secrets_realm.items():
        keycloak = keycloak.with_env(nom, valeur)
    with keycloak:
        _attendre_pret(url_hote(keycloak, 9000))
        yield url_hote(keycloak, 8080)


def _attendre_pret(url_gestion: str, delai: float = 180.0) -> None:
    limite = time.monotonic() + delai
    while time.monotonic() < limite:
        try:
            if httpx.get(f"{url_gestion}/auth/health/ready", timeout=2.0).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise TimeoutError("Keycloak n'est pas prêt à temps")


def _charge_utile(jeton: str) -> dict[str, Any]:
    """Contenu du JWT (la signature est vérifiée par les services, pas ici)."""
    partie = jeton.split(".")[1]
    contenu: dict[str, Any] = json.loads(
        base64.urlsafe_b64decode(partie + "=" * (-len(partie) % 4))
    )
    return contenu


def _jeton_services(base: str, secret: str) -> httpx.Response:
    return httpx.post(
        f"{base}{REALM}/token",
        data={"grant_type": "client_credentials", "client_id": "services", "client_secret": secret},
    )


def _connexion_pkce(base: str, utilisateur: str, mot_de_passe: str) -> dict[str, Any]:
    """Parcours complet du front : page de connexion, code, échange avec le code_verifier."""
    verificateur = secrets.token_urlsafe(48)
    defi = base64.urlsafe_b64encode(hashlib.sha256(verificateur.encode()).digest()).rstrip(b"=")
    with httpx.Client(base_url=base, timeout=10.0) as client:
        page = client.get(
            f"{REALM}/auth",
            params={
                "client_id": "frontend",
                "response_type": "code",
                "redirect_uri": REDIRECTION,
                "scope": "openid",
                "state": "etat",
                "code_challenge": defi.decode(),
                "code_challenge_method": "S256",
            },
        )
        action = re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', page.text)
        assert action, "Formulaire de connexion introuvable"
        # Keycloak pose ses cookies de session avec l'attribut Secure. Un navigateur les renvoie
        # quand même sur localhost, httpx non : on les renvoie explicitement.
        cookies = "; ".join(f"{cookie.name}={cookie.value}" for cookie in client.cookies.jar)
        retour = client.post(
            html.unescape(action.group(1)),
            data={"username": utilisateur, "password": mot_de_passe, "credentialId": ""},
            headers={"Cookie": cookies},
        )
        assert retour.status_code == 302, retour.text[:300]
        code = parse_qs(urlparse(retour.headers["location"]).query)["code"][0]
        jeton = client.post(
            f"{REALM}/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "frontend",
                "code": code,
                "redirect_uri": REDIRECTION,
                "code_verifier": verificateur,
            },
        )
    assert jeton.status_code == 200, jeton.text
    return _charge_utile(jeton.json()["access_token"])


def test_le_client_services_obtient_un_jeton_par_client_credentials(
    keycloak_url: str, secrets_realm: dict[str, str]
) -> None:
    reponse = _jeton_services(keycloak_url, secrets_realm["KEYCLOAK_SERVICES_SECRET"])

    assert reponse.status_code == 200
    jeton = _charge_utile(reponse.json()["access_token"])
    assert jeton["azp"] == "services"
    # Un compte de service n'a aucun rôle métier, mais il a le scope d'écriture d'echo.
    assert not ROLES_METIER & set(jeton["realm_access"]["roles"])
    assert "echos:write" in jeton["scope"].split()


def test_un_mauvais_secret_est_refuse(keycloak_url: str) -> None:
    assert _jeton_services(keycloak_url, "mauvais-secret").status_code == 401


@pytest.mark.parametrize(
    ("utilisateur", "variable", "role"),
    [
        ("client.test", "KEYCLOAK_MDP_CLIENT", "customer"),
        ("partenaire.test", "KEYCLOAK_MDP_PARTENAIRE", "partner"),
        ("admin.test", "KEYCLOAK_MDP_ADMIN", "admin"),
    ],
)
def test_chaque_utilisateur_de_test_a_seulement_son_role(
    keycloak_url: str, secrets_realm: dict[str, str], utilisateur: str, variable: str, role: str
) -> None:
    jeton = _connexion_pkce(keycloak_url, utilisateur, secrets_realm[variable])

    assert jeton["preferred_username"] == utilisateur
    assert ROLES_METIER & set(jeton["realm_access"]["roles"]) == {role}
    assert "echos:write" not in jeton["scope"].split()


def test_les_jetons_d_acces_durent_5_minutes(
    keycloak_url: str, secrets_realm: dict[str, str]
) -> None:
    reponse = _jeton_services(keycloak_url, secrets_realm["KEYCLOAK_SERVICES_SECRET"])
    jeton = _charge_utile(reponse.json()["access_token"])

    assert jeton["exp"] - jeton["iat"] == 300


def test_les_jetons_portent_l_audience_de_l_api(
    keycloak_url: str, secrets_realm: dict[str, str]
) -> None:
    services = _charge_utile(
        _jeton_services(keycloak_url, secrets_realm["KEYCLOAK_SERVICES_SECRET"]).json()[
            "access_token"
        ]
    )
    frontend = _connexion_pkce(keycloak_url, "client.test", secrets_realm["KEYCLOAK_MDP_CLIENT"])

    for jeton in (services, frontend):
        audiences = jeton["aud"] if isinstance(jeton["aud"], list) else [jeton["aud"]]
        assert "billetterie-api" in audiences


def test_le_frontend_exige_pkce(keycloak_url: str) -> None:
    reponse = httpx.get(
        f"{keycloak_url}{REALM}/auth",
        params={"client_id": "frontend", "response_type": "code", "redirect_uri": REDIRECTION},
    )

    # Sans code_challenge, Keycloak renvoie une erreur au lieu de la page de connexion.
    assert reponse.status_code in {302, 400}
    if reponse.status_code == 302:
        assert "error=invalid_request" in reponse.headers["location"]


def test_le_frontend_refuse_une_redirection_hors_du_domaine_local(keycloak_url: str) -> None:
    reponse = httpx.get(
        f"{keycloak_url}{REALM}/auth",
        params={
            "client_id": "frontend",
            "response_type": "code",
            "redirect_uri": "https://pirate.exemple/rappel",
            "code_challenge": "x" * 43,
            "code_challenge_method": "S256",
        },
    )

    assert reponse.status_code == 400
