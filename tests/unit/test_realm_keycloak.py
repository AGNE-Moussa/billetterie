"""Le realm versionné ne contient aucun secret : seulement des variables ${...} lues dans .env."""

import json
import re
from pathlib import Path
from typing import Any

REALM = Path(__file__).resolve().parents[2] / "infra" / "keycloak" / "realm-billetterie.json"
VARIABLE = re.compile(r"\$\{[A-Z_]+\}")


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
    assert clients["frontend"]["redirectUris"] == ["http://localhost/*"]
    assert clients["services"]["publicClient"] is False
    assert clients["services"]["serviceAccountsEnabled"] is True
    assert realm["accessTokenLifespan"] == 300


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
