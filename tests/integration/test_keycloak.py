"""Realm Keycloak « billetterie » importé depuis infra/keycloak/realm-billetterie.json.

Client Credentials pour les clients services et revendeur-test, Authorization Code + PKCE pour le
client frontend, rôles et scopes métier dans les jetons, durée de vie de 5 minutes (BIL-F09,
BIL-F13, BIL-003).
"""

import base64
import hashlib
import html
import json
import re
import secrets
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from testcontainers.core.container import DockerContainer

from commun.auth import Appelant
from commun.jetons import VerificateurJetons

IMAGE_KEYCLOAK = "quay.io/keycloak/keycloak:26.4.1"
DOSSIER_REALM = Path(__file__).resolve().parents[2] / "infra" / "keycloak"
FICHIER_REALM = DOSSIER_REALM / "realm-billetterie.json"
CHEMIN_REALM = "/auth/realms/billetterie"
REALM = f"{CHEMIN_REALM}/protocol/openid-connect"
ADMIN_REALM = "/auth/admin/realms/billetterie"
REDIRECTION = "http://localhost/rappel"
ROLES_METIER = {"customer", "partner", "admin"}
AUDIENCE = "billetterie-api"
# Compte d'administration du conteneur de test (API d'administration, CA2 de BIL-003).
ADMIN_KC = "admin.kc.test"

# Matrice de BIL-003 (docs/test-plans/BIL-003.md, Q1) : une seule table pour tous les cas.
SCOPES_METIER = frozenset(
    {"events:read", "events:write", "orders:read", "orders:write", "tickets:read"}
)
SCOPES_D_ACHAT = frozenset({"events:read", "orders:read", "orders:write", "tickets:read"})
SCOPES_SERVICES = frozenset({"echos:read", "echos:write", "seats:lock", "payments:write"})
REVENDEUR = "revendeur-test"
COMPTE_DE_SERVICE_REVENDEUR = f"service-account-{REVENDEUR}"


class Compte(NamedTuple):
    """Un compte de la matrice : utilisateur (PKCE via frontend) ou client (Client Credentials)."""

    nom: str
    flux: str
    variable: str
    role: str
    scopes: frozenset[str]


COMPTES = (
    Compte("client.test", "pkce", "KEYCLOAK_MDP_CLIENT", "customer", SCOPES_D_ACHAT),
    Compte(
        "admin.test",
        "pkce",
        "KEYCLOAK_MDP_ADMIN",
        "admin",
        frozenset({"events:read", "events:write"}),
    ),
    Compte(REVENDEUR, "client_credentials", "KEYCLOAK_REVENDEUR_SECRET", "partner", SCOPES_D_ACHAT),
)
MATRICE = {compte.nom: compte for compte in COMPTES}


@pytest.fixture(scope="module")
def mdp_admin_kc() -> str:
    """Mot de passe du compte d'administration du conteneur, tiré au hasard."""
    return secrets.token_urlsafe(16)


@contextmanager
def _keycloak(
    secrets_realm: dict[str, str],
    mdp_admin_kc: str,
    url_hote: Callable[[DockerContainer, int], str],
) -> Iterator[DockerContainer]:
    """Keycloak neuf en mode dev (base H2 interne), realm importé au démarrage."""
    keycloak = (
        DockerContainer(IMAGE_KEYCLOAK)
        .with_command("start-dev --import-realm")
        .with_env("KC_HTTP_RELATIVE_PATH", "/auth")
        .with_env("KC_HEALTH_ENABLED", "true")
        .with_env("KC_BOOTSTRAP_ADMIN_USERNAME", ADMIN_KC)
        .with_env("KC_BOOTSTRAP_ADMIN_PASSWORD", mdp_admin_kc)
        .with_volume_mapping(str(DOSSIER_REALM), "/opt/keycloak/data/import")
        .with_exposed_ports(8080, 9000)
    )
    for nom, valeur in secrets_realm.items():
        keycloak = keycloak.with_env(nom, valeur)
    with keycloak:
        _attendre_pret(url_hote(keycloak, 9000))
        yield keycloak


@pytest.fixture(scope="module")
def keycloak_url(
    secrets_realm: dict[str, str],
    mdp_admin_kc: str,
    url_hote: Callable[[DockerContainer, int], str],
) -> Iterator[str]:
    """Keycloak partagé par les tests du module."""
    with _keycloak(secrets_realm, mdp_admin_kc, url_hote) as keycloak:
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


def _jeton_client(
    base: str, client_id: str, secret: str, scope: str | None = None
) -> httpx.Response:
    donnees = {"grant_type": "client_credentials", "client_id": client_id, "client_secret": secret}
    if scope is not None:
        donnees["scope"] = scope
    return httpx.post(f"{base}{REALM}/token", data=donnees)


def _jeton_services(base: str, secret: str) -> httpx.Response:
    return _jeton_client(base, "services", secret)


def _defi_pkce() -> tuple[str, str]:
    """(code_verifier, code_challenge S256)."""
    verificateur = secrets.token_urlsafe(48)
    defi = base64.urlsafe_b64encode(hashlib.sha256(verificateur.encode()).digest()).rstrip(b"=")
    return verificateur, defi.decode()


def _jeton_pkce(base: str, utilisateur: str, mot_de_passe: str, scope: str = "openid") -> str:
    """Parcours complet du front : page de connexion, code, échange avec le code_verifier."""
    verificateur, defi = _defi_pkce()
    with httpx.Client(base_url=base, timeout=10.0) as client:
        page = client.get(
            f"{REALM}/auth",
            params={
                "client_id": "frontend",
                "response_type": "code",
                "redirect_uri": REDIRECTION,
                "scope": scope,
                "state": "etat",
                "code_challenge": defi,
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
    acces: str = jeton.json()["access_token"]
    return acces


def _connexion_pkce(
    base: str, utilisateur: str, mot_de_passe: str, scope: str = "openid"
) -> dict[str, Any]:
    return _charge_utile(_jeton_pkce(base, utilisateur, mot_de_passe, scope))


def _jeton_du_compte(base: str, secrets_realm: dict[str, str], compte: Compte) -> str:
    """Jeton d'accès brut d'un compte de la matrice, par son flux."""
    if compte.flux == "pkce":
        return _jeton_pkce(base, compte.nom, secrets_realm[compte.variable])
    reponse = _jeton_client(base, compte.nom, secrets_realm[compte.variable])
    assert reponse.status_code == 200, reponse.text
    acces: str = reponse.json()["access_token"]
    return acces


def _scopes_metier(jeton: dict[str, Any]) -> set[str]:
    return set(jeton.get("scope", "").split()) & SCOPES_METIER


def _roles_metier(jeton: dict[str, Any]) -> set[str]:
    return ROLES_METIER & set(jeton.get("realm_access", {}).get("roles", []))


def _audiences(jeton: dict[str, Any]) -> list[str]:
    aud = jeton.get("aud", [])
    return aud if isinstance(aud, list) else [aud]


# --- Instantané du realm (CA2 de BIL-003, Q11) -----------------------------------------------
#
# Champs comparés : scopes (nom, protocole, attributs déclarés), scopes par défaut et optionnels
# du realm et des clients, scopeMappings, rôles, clients (réglages déclarés, mappers),
# utilisateurs et leurs rôles, rôles des comptes de service. Ni `id` ni secret ni mot de passe.
# Les éléments lus sont ceux que déclare le JSON ; les rôles sont restreints aux rôles du realm
# déclarés dans le JSON (Keycloak ajoute ses propres rôles par défaut).

CHAMPS_CLIENT = (
    "name",
    "enabled",
    "publicClient",
    "protocol",
    "clientAuthenticatorType",
    "standardFlowEnabled",
    "directAccessGrantsEnabled",
    "implicitFlowEnabled",
    "serviceAccountsEnabled",
)
LISTES_CLIENT = ("redirectUris", "webOrigins")
CHAMPS_UTILISATEUR = ("enabled", "email", "firstName", "lastName", "emailVerified")
VARIABLE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _realm_json() -> dict[str, Any]:
    contenu: dict[str, Any] = json.loads(FICHIER_REALM.read_text(encoding="utf-8"))
    return contenu


def _substituer(valeur: Any, variables: dict[str, str]) -> Any:
    """Remplace les ${VARIABLE} connues, comme Keycloak à l'import ; les autres restent."""
    if isinstance(valeur, str):
        return VARIABLE.sub(lambda m: variables.get(m.group(1), m.group(0)), valeur)
    if isinstance(valeur, list):
        return [_substituer(element, variables) for element in valeur]
    if isinstance(valeur, dict):
        return {cle: _substituer(element, variables) for cle, element in valeur.items()}
    return valeur


def _roles_declares(realm: dict[str, Any]) -> set[str]:
    return {role["name"] for role in realm.get("roles", {}).get("realm", [])}


def _mappers(mappers: list[dict[str, Any]], declares: list[dict[str, Any]]) -> dict[str, Any]:
    par_nom = {mapper["name"]: mapper for mapper in mappers}
    resultat: dict[str, Any] = {}
    for declare in declares:
        lu = par_nom.get(declare["name"], {})
        config = lu.get("config", {})
        resultat[declare["name"]] = {
            "protocolMapper": lu.get("protocolMapper"),
            "config": {cle: config.get(cle) for cle in declare.get("config", {})},
        }
    return resultat


def _instantane_json(variables: dict[str, str]) -> dict[str, Any]:
    """Instantané attendu, calculé depuis le JSON versionné (variables substituées)."""
    realm = _substituer(_realm_json(), variables)
    roles = _roles_declares(realm)
    scopes = {
        scope["name"]: {
            "protocol": scope.get("protocol"),
            "attributes": dict(scope.get("attributes", {})),
        }
        for scope in realm.get("clientScopes", [])
    }
    mappings: dict[str, set[str]] = {f"clientScope:{nom}": set() for nom in scopes}
    for mapping in realm.get("scopeMappings", []):
        cible = (
            f"clientScope:{mapping['clientScope']}"
            if "clientScope" in mapping
            else f"client:{mapping['client']}"
        )
        mappings.setdefault(cible, set()).update(set(mapping.get("roles", [])) & roles)
    clients: dict[str, Any] = {}
    for client in realm.get("clients", []):
        attendu: dict[str, Any] = {
            champ: client[champ] for champ in CHAMPS_CLIENT if champ in client
        }
        for champ in LISTES_CLIENT:
            if champ in client:
                attendu[champ] = sorted(client[champ])
        for champ in ("defaultClientScopes", "optionalClientScopes"):
            if champ in client:
                attendu[champ] = sorted(client[champ])
        if "attributes" in client:
            attendu["attributes"] = dict(client["attributes"])
        if "protocolMappers" in client:
            attendu["protocolMappers"] = _mappers(
                client["protocolMappers"], client["protocolMappers"]
            )
        clients[client["clientId"]] = attendu
    utilisateurs: dict[str, Any] = {}
    for utilisateur in realm.get("users", []):
        attendu = {
            champ: utilisateur[champ] for champ in CHAMPS_UTILISATEUR if champ in utilisateur
        }
        attendu["roles"] = sorted(set(utilisateur.get("realmRoles", [])) & roles)
        if "serviceAccountClientId" in utilisateur:
            attendu["serviceAccountClientId"] = utilisateur["serviceAccountClientId"]
        utilisateurs[utilisateur["username"]] = attendu
    return {
        "roles": {
            role["name"]: role.get("description")
            for role in realm.get("roles", {}).get("realm", [])
        },
        "clientScopes": scopes,
        "defaultDefaultClientScopes": sorted(realm.get("defaultDefaultClientScopes", [])),
        "defaultOptionalClientScopes": sorted(realm.get("defaultOptionalClientScopes", [])),
        "scopeMappings": {cible: sorted(valeurs) for cible, valeurs in mappings.items()},
        "clients": clients,
        "users": utilisateurs,
    }


def _jeton_admin(base: str, mdp_admin_kc: str) -> str:
    reponse = httpx.post(
        f"{base}/auth/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": ADMIN_KC,
            "password": mdp_admin_kc,
        },
    )
    assert reponse.status_code == 200, reponse.text
    jeton: str = reponse.json()["access_token"]
    return jeton


def _noms(elements: list[dict[str, Any]]) -> list[str]:
    return sorted(element["name"] for element in elements)


def _instantane_keycloak(base: str, mdp_admin_kc: str) -> dict[str, Any]:
    """Instantané lu dans le realm importé, par l'API d'administration, sur les champs du JSON."""
    realm = _realm_json()
    roles = _roles_declares(realm)
    entetes = {"Authorization": f"Bearer {_jeton_admin(base, mdp_admin_kc)}"}
    with httpx.Client(base_url=f"{base}{ADMIN_REALM}", headers=entetes, timeout=10.0) as api:

        def lire(chemin: str, **params: Any) -> Any:
            reponse = api.get(chemin, params=params)
            assert reponse.status_code == 200, (chemin, reponse.status_code, reponse.text[:300])
            return reponse.json()

        def roles_metier(chemin: str) -> list[str]:
            return sorted({role["name"] for role in lire(chemin)} & roles)

        lus_roles = {role["name"]: role.get("description") for role in lire("/roles")}
        tous_scopes = {scope["name"]: scope for scope in lire("/client-scopes")}
        scopes: dict[str, Any] = {}
        mappings: dict[str, list[str]] = {}
        for declare in realm.get("clientScopes", []):
            lu = tous_scopes.get(declare["name"])
            if lu is None:
                continue
            attributs = lu.get("attributes", {})
            scopes[declare["name"]] = {
                "protocol": lu.get("protocol"),
                "attributes": {cle: attributs.get(cle) for cle in declare.get("attributes", {})},
            }
            mappings[f"clientScope:{declare['name']}"] = roles_metier(
                f"/client-scopes/{lu['id']}/scope-mappings/realm"
            )

        clients: dict[str, Any] = {}
        identifiants_clients: dict[str, str] = {}
        for declare in realm.get("clients", []):
            trouves = lire("/clients", clientId=declare["clientId"])
            if not trouves:
                continue
            lu = trouves[0]
            identifiants_clients[declare["clientId"]] = lu["id"]
            obtenu: dict[str, Any] = {
                champ: lu.get(champ) for champ in CHAMPS_CLIENT if champ in declare
            }
            for champ in LISTES_CLIENT:
                if champ in declare:
                    obtenu[champ] = sorted(lu.get(champ, []))
            if "defaultClientScopes" in declare:
                obtenu["defaultClientScopes"] = _noms(
                    lire(f"/clients/{lu['id']}/default-client-scopes")
                )
            if "optionalClientScopes" in declare:
                obtenu["optionalClientScopes"] = _noms(
                    lire(f"/clients/{lu['id']}/optional-client-scopes")
                )
            if "attributes" in declare:
                attributs = lu.get("attributes", {})
                obtenu["attributes"] = {cle: attributs.get(cle) for cle in declare["attributes"]}
            if "protocolMappers" in declare:
                obtenu["protocolMappers"] = _mappers(
                    lu.get("protocolMappers", []), declare["protocolMappers"]
                )
            clients[declare["clientId"]] = obtenu
        for mapping in realm.get("scopeMappings", []):
            if "client" in mapping and mapping["client"] in identifiants_clients:
                mappings[f"client:{mapping['client']}"] = roles_metier(
                    f"/clients/{identifiants_clients[mapping['client']]}/scope-mappings/realm"
                )

        utilisateurs: dict[str, Any] = {}
        for declare in realm.get("users", []):
            client_du_compte = declare.get("serviceAccountClientId")
            if client_du_compte is not None:
                if client_du_compte not in identifiants_clients:
                    continue
                lu = lire(f"/clients/{identifiants_clients[client_du_compte]}/service-account-user")
            else:
                trouves = lire("/users", username=declare["username"], exact="true")
                if not trouves:
                    continue
                lu = trouves[0]
            obtenu = {champ: lu.get(champ) for champ in CHAMPS_UTILISATEUR if champ in declare}
            obtenu["roles"] = roles_metier(f"/users/{lu['id']}/role-mappings/realm")
            if client_du_compte is not None:
                obtenu["serviceAccountClientId"] = client_du_compte
            utilisateurs[lu["username"]] = obtenu

        return {
            "roles": {nom: lus_roles.get(nom) for nom in roles if nom in lus_roles},
            "clientScopes": scopes,
            "defaultDefaultClientScopes": _noms(lire("/default-default-client-scopes")),
            "defaultOptionalClientScopes": _noms(lire("/default-optional-client-scopes")),
            "scopeMappings": mappings,
            "clients": clients,
            "users": utilisateurs,
        }


def _verifier_les_scopes_des_trois_comptes(base: str, secrets_realm: dict[str, str]) -> None:
    for compte in COMPTES:
        jeton = _charge_utile(_jeton_du_compte(base, secrets_realm, compte))
        assert _scopes_metier(jeton) == set(compte.scopes), compte.nom
        assert _roles_metier(jeton) == {compte.role}, compte.nom


# --- BIL-F09 et BIL-F13 -----------------------------------------------------------------------


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
        assert AUDIENCE in _audiences(jeton)


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


# --- BIL-003, CA1 : les trois comptes obtiennent un jeton avec les bons scopes ---------------


def test_le_client_test_obtient_un_jeton_avec_les_scopes_d_achat(
    keycloak_url: str, secrets_realm: dict[str, str]
) -> None:
    compte = MATRICE["client.test"]

    jeton = _connexion_pkce(keycloak_url, compte.nom, secrets_realm[compte.variable])

    assert _scopes_metier(jeton) == set(compte.scopes)
    assert _roles_metier(jeton) == {"customer"}


def test_l_admin_organisateur_obtient_un_jeton_avec_events_write(
    keycloak_url: str, secrets_realm: dict[str, str]
) -> None:
    compte = MATRICE["admin.test"]

    jeton = _connexion_pkce(keycloak_url, compte.nom, secrets_realm[compte.variable])

    assert _scopes_metier(jeton) == {"events:read", "events:write"}
    assert _roles_metier(jeton) == {"admin"}


def test_le_revendeur_obtient_un_jeton_par_client_credentials_avec_ses_quatre_scopes(
    keycloak_url: str, secrets_realm: dict[str, str]
) -> None:
    reponse = _jeton_client(keycloak_url, REVENDEUR, secrets_realm["KEYCLOAK_REVENDEUR_SECRET"])

    assert reponse.status_code == 200, reponse.text
    jeton = _charge_utile(reponse.json()["access_token"])
    assert _scopes_metier(jeton) == {"events:read", "orders:read", "orders:write", "tickets:read"}
    assert jeton["azp"] == REVENDEUR
    assert _roles_metier(jeton) == {"partner"}
    assert AUDIENCE in _audiences(jeton)
    assert jeton["exp"] - jeton["iat"] == 300


def test_le_revendeur_avec_un_mauvais_secret_est_refuse(
    keycloak_url: str, secrets_realm: dict[str, str]
) -> None:
    # Le client existe et accepte son vrai secret : le refus vient bien du secret.
    bon = _jeton_client(keycloak_url, REVENDEUR, secrets_realm["KEYCLOAK_REVENDEUR_SECRET"])
    assert bon.status_code == 200, f"Client {REVENDEUR} absent ou refusé : {bon.text}"

    assert _jeton_client(keycloak_url, REVENDEUR, "mauvais-secret").status_code == 401


def test_le_revendeur_ne_peut_pas_obtenir_events_write_en_le_demandant(
    keycloak_url: str, secrets_realm: dict[str, str]
) -> None:
    reponse = _jeton_client(
        keycloak_url, REVENDEUR, secrets_realm["KEYCLOAK_REVENDEUR_SECRET"], scope="events:write"
    )

    assert reponse.status_code in {200, 400}, reponse.text
    if reponse.status_code == 400:
        assert reponse.json()["error"] == "invalid_scope"
    else:
        jeton = _charge_utile(reponse.json()["access_token"])
        assert "events:write" not in jeton["scope"].split()


def test_le_jeton_du_revendeur_ne_porte_aucun_scope_de_service(
    keycloak_url: str, secrets_realm: dict[str, str]
) -> None:
    reponse = _jeton_client(keycloak_url, REVENDEUR, secrets_realm["KEYCLOAK_REVENDEUR_SECRET"])

    assert reponse.status_code == 200, reponse.text
    scopes = set(_charge_utile(reponse.json()["access_token"])["scope"].split())
    assert not scopes & SCOPES_SERVICES, sorted(scopes & SCOPES_SERVICES)


def test_le_revendeur_ne_peut_pas_obtenir_offline_access_en_le_demandant(
    keycloak_url: str, secrets_realm: dict[str, str]
) -> None:
    secret = secrets_realm["KEYCLOAK_REVENDEUR_SECRET"]
    # Le client existe et obtient un jeton sans scope demandé : un refus ne viendra que du scope.
    existe = _jeton_client(keycloak_url, REVENDEUR, secret)
    assert existe.status_code == 200, f"Client {REVENDEUR} absent ou refusé : {existe.text}"

    reponse = _jeton_client(keycloak_url, REVENDEUR, secret, scope="offline_access")

    assert reponse.status_code in {200, 400}, reponse.text
    if reponse.status_code == 400:
        assert reponse.json()["error"] == "invalid_scope"
    else:
        corps = reponse.json()
        jeton = _charge_utile(corps["access_token"])
        assert "offline_access" not in jeton["scope"].split()
        assert "refresh_token" not in corps


def test_le_client_ne_peut_pas_obtenir_events_write_en_le_demandant(
    keycloak_url: str, secrets_realm: dict[str, str]
) -> None:
    jeton = _connexion_pkce(
        keycloak_url,
        "client.test",
        secrets_realm["KEYCLOAK_MDP_CLIENT"],
        scope="openid events:write",
    )

    assert "events:write" not in jeton["scope"].split()


def test_le_client_revendeur_refuse_le_flux_navigateur(
    keycloak_url: str, secrets_realm: dict[str, str]
) -> None:
    # Le client existe : un refus pour « client inconnu » ne prouverait rien.
    existe = _jeton_client(keycloak_url, REVENDEUR, secrets_realm["KEYCLOAK_REVENDEUR_SECRET"])
    assert existe.status_code == 200, f"Client {REVENDEUR} absent ou refusé : {existe.text}"
    _verificateur, defi = _defi_pkce()

    reponse = httpx.get(
        f"{keycloak_url}{REALM}/auth",
        params={
            "client_id": REVENDEUR,
            "response_type": "code",
            "redirect_uri": REDIRECTION,
            "scope": "openid",
            "state": "etat",
            "code_challenge": defi,
            "code_challenge_method": "S256",
        },
    )

    assert 'id="kc-form-login"' not in reponse.text
    assert reponse.status_code in {302, 400}
    if reponse.status_code == 302:
        assert "error=unauthorized_client" in reponse.headers["location"]


def test_le_client_services_n_obtient_aucun_scope_metier_d_utilisateur(
    keycloak_url: str, secrets_realm: dict[str, str]
) -> None:
    reponse = _jeton_services(keycloak_url, secrets_realm["KEYCLOAK_SERVICES_SECRET"])

    assert reponse.status_code == 200
    scopes = set(_charge_utile(reponse.json()["access_token"])["scope"].split())
    assert not scopes & SCOPES_METIER
    assert "echos:write" in scopes
    assert {"seats:lock", "payments:write"} <= scopes


@pytest.mark.anyio
@pytest.mark.parametrize("compte", COMPTES, ids=[compte.nom for compte in COMPTES])
async def test_l_appelant_lu_dans_un_vrai_jeton_porte_les_scopes_et_le_role_attendus(
    keycloak_url: str, secrets_realm: dict[str, str], compte: Compte
) -> None:
    jeton = _jeton_du_compte(keycloak_url, secrets_realm, compte)
    verificateur = VerificateurJetons.depuis_jwks(
        f"{keycloak_url}{REALM}/certs", f"{keycloak_url}{CHEMIN_REALM}", AUDIENCE
    )
    try:
        claims = await verificateur.verifier(jeton)
    finally:
        await verificateur.aclose()

    appelant = Appelant.depuis_claims(claims)
    assert appelant.scopes & SCOPES_METIER == compte.scopes
    assert appelant.roles & ROLES_METIER == {compte.role}


# --- BIL-003, CA2 : le realm est réimporté à l'identique au redémarrage ----------------------


def _verifier_couverture_bil_003(instantane: dict[str, Any]) -> None:
    """Le realm importé contient bien ce que BIL-003 ajoute (sinon l'égalité ne prouve rien)."""
    assert set(instantane["clientScopes"]) >= SCOPES_METIER, sorted(instantane["clientScopes"])
    assert {"seats:lock", "payments:write"} <= set(instantane["clientScopes"])
    assert REVENDEUR in instantane["clients"], sorted(instantane["clients"])
    compte = instantane["users"].get(COMPTE_DE_SERVICE_REVENDEUR, {})
    assert compte.get("roles") == ["partner"], instantane["users"]
    assert "partenaire.test" not in instantane["users"]


def test_le_realm_importe_correspond_au_json_versionne(
    keycloak_url: str, secrets_realm: dict[str, str], mdp_admin_kc: str
) -> None:
    attendu = _instantane_json(secrets_realm)

    obtenu = _instantane_keycloak(keycloak_url, mdp_admin_kc)

    assert obtenu == attendu
    _verifier_couverture_bil_003(obtenu)


def test_apres_redemarrage_de_keycloak_le_realm_et_les_jetons_sont_identiques(
    secrets_realm: dict[str, str],
    mdp_admin_kc: str,
    url_hote: Callable[[DockerContainer, int], str],
) -> None:
    with _keycloak(secrets_realm, mdp_admin_kc, url_hote) as keycloak:
        avant = _instantane_keycloak(url_hote(keycloak, 8080), mdp_admin_kc)

        # Même conteneur arrêté puis relancé : la base H2 est gardée, les ports changent.
        conteneur = keycloak.get_wrapped_container()
        conteneur.stop()
        conteneur.start()
        _attendre_pret(url_hote(keycloak, 9000))
        base = url_hote(keycloak, 8080)
        apres = _instantane_keycloak(base, mdp_admin_kc)

        assert apres == avant
        _verifier_couverture_bil_003(apres)
        _verifier_les_scopes_des_trois_comptes(base, secrets_realm)


def test_deux_imports_neufs_donnent_la_meme_configuration(
    keycloak_url: str,
    secrets_realm: dict[str, str],
    mdp_admin_kc: str,
    url_hote: Callable[[DockerContainer, int], str],
) -> None:
    premier = _instantane_keycloak(keycloak_url, mdp_admin_kc)

    with _keycloak(secrets_realm, mdp_admin_kc, url_hote) as second:
        deuxieme = _instantane_keycloak(url_hote(second, 8080), mdp_admin_kc)

    assert deuxieme == premier
    _verifier_couverture_bil_003(deuxieme)
