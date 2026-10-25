"""Le realm versionné ne contient aucun secret : seulement des variables ${...} lues dans .env."""

import json
import re
from pathlib import Path
from typing import Any

import yaml

RACINE = Path(__file__).resolve().parents[2]
REALM = RACINE / "infra" / "keycloak" / "realm-billetterie.json"
VARIABLE = re.compile(r"\$\{[A-Z_]+\}")
# Origine publique du front (BIL-F29) : http://localhost en local, https://<domaine> en démo.
URL_FRONT = "KEYCLOAK_URL_FRONT"
ADRESSE_FRONT = re.compile(r"\$\{" + URL_FRONT + r"\}(/\*)?")


def _realm() -> dict[str, Any]:
    contenu: dict[str, Any] = json.loads(REALM.read_text(encoding="utf-8"))
    return contenu


def test_les_secrets_de_clients_sont_des_variables() -> None:
    for client in _realm()["clients"]:
        if "secret" in client:
            assert VARIABLE.fullmatch(client["secret"]), client["clientId"]


def test_les_mots_de_passe_des_utilisateurs_sont_des_variables() -> None:
    for utilisateur in _realm()["users"]:
        for identifiant in utilisateur.get("credentials", []):
            assert VARIABLE.fullmatch(identifiant["value"]), utilisateur["username"]


def test_roles_et_clients_attendus() -> None:
    realm = _realm()

    assert {role["name"] for role in realm["roles"]["realm"]} == {"customer", "partner", "admin"}
    clients = {client["clientId"]: client for client in realm["clients"]}
    assert clients["frontend"]["publicClient"] is True
    assert clients["frontend"]["attributes"]["pkce.code.challenge.method"] == "S256"
    assert clients["frontend"]["redirectUris"] == ["${KEYCLOAK_URL_FRONT}/*"]
    assert clients["services"]["publicClient"] is False
    assert clients["services"]["serviceAccountsEnabled"] is True
    assert realm["accessTokenLifespan"] == 300


def test_les_redirect_uris_du_client_frontend_sont_parametrees_par_le_domaine() -> None:
    clients = {client["clientId"]: client for client in _realm()["clients"]}
    frontend = clients["frontend"]
    deconnexion = frontend["attributes"]["post.logout.redirect.uris"].split("##")
    adresses = {
        "redirectUris": frontend["redirectUris"],
        "webOrigins": frontend["webOrigins"],
        "post.logout.redirect.uris": deconnexion,
    }

    for champ, valeurs in adresses.items():
        assert valeurs, champ
        for valeur in valeurs:
            assert ADRESSE_FRONT.fullmatch(valeur), f"{champ} : {valeur}"


def test_en_local_la_variable_du_front_vaut_localhost() -> None:
    compose = yaml.safe_load((RACINE / "compose.yaml").read_text(encoding="utf-8"))
    environnement = compose["services"]["keycloak"]["environment"]
    lignes = (RACINE / ".env.example").read_text(encoding="utf-8").splitlines()

    assert "${" + URL_FRONT in str(environnement.get(URL_FRONT, "")), (
        f"compose.yaml doit passer {URL_FRONT} à Keycloak"
    )
    assert f"{URL_FRONT}=" in lignes, f".env.example doit documenter {URL_FRONT}, valeur vide"


def test_les_jetons_des_deux_clients_visent_l_api() -> None:
    # Le vérificateur de la gateway exige l'audience billetterie-api (claim aud).
    for client in _realm()["clients"]:
        audiences = [
            mapper["config"]["included.custom.audience"]
            for mapper in client.get("protocolMappers", [])
            if mapper["protocolMapper"] == "oidc-audience-mapper"
        ]
        assert audiences == ["billetterie-api"], client["clientId"]


def test_les_scopes_integres_de_keycloak_sont_declares() -> None:
    # Déclarer clientScopes remplace les scopes intégrés de Keycloak : sans roles ni basic, les
    # jetons perdraient realm_access et sub. Ils sont donc listés dans le realm.
    realm = _realm()
    noms = {scope["name"] for scope in realm["clientScopes"]}

    assert {"roles", "basic", "profile", "email", "web-origins", "acr"} <= noms
    assert set(realm["defaultDefaultClientScopes"]) <= noms
    assert set(realm["defaultOptionalClientScopes"]) <= noms


def test_le_scope_echos_write_est_donne_au_seul_client_services() -> None:
    realm = _realm()
    clients = {client["clientId"]: client for client in realm["clients"]}

    assert "echos:write" in {scope["name"] for scope in realm["clientScopes"]}
    assert "echos:write" in clients["services"]["defaultClientScopes"]
    assert "echos:write" not in realm["defaultDefaultClientScopes"]
    assert "echos:write" not in clients["frontend"].get("defaultClientScopes", [])


def test_le_realm_donne_le_scope_echos_read_par_defaut_au_client_services() -> None:
    realm = _realm()
    clients = {client["clientId"]: client for client in realm["clients"]}

    assert "echos:read" in {scope["name"] for scope in realm["clientScopes"]}
    assert "echos:read" in clients["services"]["defaultClientScopes"]


def test_le_scope_echos_read_n_est_donne_qu_au_client_services() -> None:
    # Garde-fou : le client public du front ne doit jamais pouvoir obtenir echos:read.
    realm = _realm()
    clients = {client["clientId"]: client for client in realm["clients"]}

    assert "echos:read" not in clients["frontend"].get("defaultClientScopes", [])
    assert "echos:read" not in clients["frontend"].get("optionalClientScopes", [])
    assert "echos:read" not in realm["defaultDefaultClientScopes"]
    assert "echos:read" not in realm["defaultOptionalClientScopes"]
    detenteurs = {
        nom
        for nom, client in clients.items()
        if "echos:read"
        in client.get("defaultClientScopes", []) + client.get("optionalClientScopes", [])
    }
    assert detenteurs == {"services"}
