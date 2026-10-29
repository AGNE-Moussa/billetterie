"""Comptes de test du realm (BIL-003) : chacun obtient ses scopes métier sur la plateforme locale.

Joués contre `make up` par `make test-smoke`, jamais par la CI. Le revendeur passe par Client
Credentials, `client.test` et `admin.test` par Authorization Code + PKCE via le client `frontend`,
comme le front, à travers la gateway. Secrets et mots de passe lus dans `.env`, jamais écrits ici.
Chaque test est ignoré si la gateway ne répond pas ou si son secret manque.
"""

import base64
import hashlib
import html
import json
import re
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

pytestmark = pytest.mark.smoke

GATEWAY = "http://localhost"
REDIRECTION = f"{GATEWAY}/rappel"
RACINE = Path(__file__).resolve().parents[2]
ROLES_METIER = {"customer", "partner", "admin"}
SCOPES_METIER = {"events:read", "events:write", "orders:read", "orders:write", "tickets:read"}
SCOPES_D_ACHAT = {"events:read", "orders:read", "orders:write", "tickets:read"}

# (utilisateur, variable du mot de passe dans .env, rôle, scopes métier attendus)
UTILISATEURS = [
    ("client.test", "KEYCLOAK_MDP_CLIENT", "customer", SCOPES_D_ACHAT),
    ("admin.test", "KEYCLOAK_MDP_ADMIN", "admin", {"events:read", "events:write"}),
]
IDS = [utilisateur for utilisateur, _, _, _ in UTILISATEURS]


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


def _charge_utile(jeton: str) -> dict[str, Any]:
    """Contenu du JWT (la signature est vérifiée par les services, pas ici)."""
    partie = jeton.split(".")[1]
    contenu: dict[str, Any] = json.loads(
        base64.urlsafe_b64decode(partie + "=" * (-len(partie) % 4))
    )
    return contenu


def _scopes_metier(charge: dict[str, Any]) -> set[str]:
    return set(str(charge.get("scope", "")).split()) & SCOPES_METIER


def _roles_metier(charge: dict[str, Any]) -> set[str]:
    return set(charge.get("realm_access", {}).get("roles", [])) & ROLES_METIER


@pytest.fixture(scope="module")
def env() -> dict[str, str]:
    return _lire_env()


@pytest.fixture(scope="module")
def oidc(env: dict[str, str]) -> str:
    """Base OpenID Connect du realm, derrière la gateway."""
    try:
        httpx.get(f"{GATEWAY}/", timeout=3.0)
    except httpx.HTTPError:
        pytest.skip(f"La gateway ne répond pas sur {GATEWAY} : lancer make up")
    realm = env.get("KEYCLOAK_REALM") or "billetterie"
    return f"{GATEWAY}/auth/realms/{realm}/protocol/openid-connect"


def _jeton_pkce(oidc: str, utilisateur: str, mot_de_passe: str) -> str:
    """Parcours du front : page de connexion, code, échange avec le code_verifier."""
    verificateur = secrets.token_urlsafe(48)
    defi = base64.urlsafe_b64encode(hashlib.sha256(verificateur.encode()).digest()).rstrip(b"=")
    with httpx.Client(timeout=10.0) as client:
        page = client.get(
            f"{oidc}/auth",
            params={
                "client_id": "frontend",
                "response_type": "code",
                "redirect_uri": REDIRECTION,
                "scope": "openid",
                "state": secrets.token_urlsafe(8),
                "code_challenge": defi.decode(),
                "code_challenge_method": "S256",
            },
        )
        action = re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', page.text)
        assert action, f"Formulaire de connexion introuvable ({page.status_code})"
        # Keycloak pose ses cookies de session avec l'attribut Secure. Un navigateur les renvoie
        # quand même sur localhost, httpx non : on les renvoie explicitement.
        cookies = "; ".join(f"{cookie.name}={cookie.value}" for cookie in client.cookies.jar)
        retour = client.post(
            html.unescape(action.group(1)),
            data={"username": utilisateur, "password": mot_de_passe, "credentialId": ""},
            headers={"Cookie": cookies},
        )
        assert retour.status_code == 302, (
            f"{utilisateur} : connexion refusée ({retour.status_code})"
        )
        code = parse_qs(urlparse(retour.headers["location"]).query)["code"][0]
        jeton = client.post(
            f"{oidc}/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "frontend",
                "code": code,
                "redirect_uri": REDIRECTION,
                "code_verifier": verificateur,
            },
        )
    assert jeton.status_code == 200, f"{utilisateur} : échange du code refusé ({jeton.status_code})"
    return str(jeton.json()["access_token"])


def test_le_revendeur_obtient_un_jeton_sur_la_plateforme_locale(
    oidc: str, env: dict[str, str]
) -> None:
    secret = env.get("KEYCLOAK_REVENDEUR_SECRET")
    if not secret:
        pytest.skip("KEYCLOAK_REVENDEUR_SECRET absent de .env")

    reponse = httpx.post(
        f"{oidc}/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "revendeur-test",
            "client_secret": secret,
        },
        timeout=10.0,
    )

    assert reponse.status_code == 200, f"Keycloak refuse le revendeur ({reponse.status_code})"
    charge = _charge_utile(reponse.json()["access_token"])
    assert _scopes_metier(charge) == SCOPES_D_ACHAT
    assert _roles_metier(charge) == {"partner"}
    assert "billetterie-api" in charge["aud"]


@pytest.mark.parametrize(("utilisateur", "variable", "role", "scopes"), UTILISATEURS, ids=IDS)
def test_les_utilisateurs_de_test_obtiennent_leurs_scopes_sur_la_plateforme_locale(
    oidc: str,
    env: dict[str, str],
    utilisateur: str,
    variable: str,
    role: str,
    scopes: set[str],
) -> None:
    mot_de_passe = env.get(variable)
    if not mot_de_passe:
        pytest.skip(f"{variable} absent de .env")

    charge = _charge_utile(_jeton_pkce(oidc, utilisateur, mot_de_passe))

    assert _scopes_metier(charge) == scopes
    assert _roles_metier(charge) == {role}
