"""Le realm versionné ne contient aucun secret : seulement des variables ${...} lues dans .env."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[2]
REALM = RACINE / "infra" / "keycloak" / "realm-billetterie.json"
VARIABLE = re.compile(r"\$\{[A-Z_]+\}")
# Origine publique du front (BIL-F29) : http://localhost en local, https://<domaine> en démo.
URL_FRONT = "KEYCLOAK_URL_FRONT"
ADRESSE_FRONT = re.compile(r"\$\{" + URL_FRONT + r"\}(/\*)?")

# Scopes métier (BIL-003, étape 2) et rôles qui peuvent les recevoir (plan BIL-003, Q1 et Q2).
SCOPES_METIER = {"events:read", "events:write", "orders:read", "orders:write", "tickets:read"}
ROLES_METIER = {"customer", "partner", "admin"}
ROLES_PAR_SCOPE = {
    "events:read": {"customer", "partner", "admin"},
    "events:write": {"admin"},
    "orders:read": {"customer", "partner"},
    "orders:write": {"customer", "partner"},
    "tickets:read": {"customer", "partner"},
}
# Revendeur en Client Credentials (plan BIL-003, Q4) : scopes de docs/conception.md.
REVENDEUR = "revendeur-test"
SCOPES_REVENDEUR = {"events:read", "orders:read", "orders:write", "tickets:read"}
# Scopes de service, donnés au seul client services (plan BIL-003, Q8).
SCOPES_SERVICE = {"seats:lock", "payments:write"}


def _realm() -> dict[str, Any]:
    contenu: dict[str, Any] = json.loads(REALM.read_text(encoding="utf-8"))
    return contenu


def _clients(realm: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {client["clientId"]: client for client in realm["clients"]}


def _scopes_du_client(client: dict[str, Any]) -> tuple[set[str], set[str]]:
    return set(client.get("defaultClientScopes", [])), set(client.get("optionalClientScopes", []))


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
    assert REVENDEUR in clients, f"client {REVENDEUR} absent du realm"
    assert clients[REVENDEUR]["publicClient"] is False
    assert clients[REVENDEUR]["serviceAccountsEnabled"] is True
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


def test_les_jetons_de_tous_les_clients_visent_l_api() -> None:
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


# --- BIL-003 : scopes métier, revendeur de test (CA1) ---


def test_le_realm_declare_les_cinq_scopes_metier() -> None:
    declares = {scope["name"]: scope for scope in _realm()["clientScopes"]}

    assert set(declares) >= SCOPES_METIER, sorted(SCOPES_METIER - set(declares))
    for nom in SCOPES_METIER:
        assert declares[nom]["protocol"] == "openid-connect", nom
        assert declares[nom]["attributes"]["include.in.token.scope"] == "true", nom


def test_aucun_scope_metier_n_est_donne_par_defaut_a_tout_le_realm() -> None:
    realm = _realm()

    assert not SCOPES_METIER & set(realm["defaultDefaultClientScopes"])
    assert not SCOPES_METIER & set(realm["defaultOptionalClientScopes"])


@pytest.mark.parametrize("scope", sorted(ROLES_PAR_SCOPE))
def test_chaque_scope_metier_est_limite_aux_roles_prevus(scope: str) -> None:
    # Role scope mapping : Keycloak n'émet le scope que si l'utilisateur a l'un de ces rôles.
    roles = {
        role
        for correspondance in _realm().get("scopeMappings", [])
        if correspondance.get("clientScope") == scope
        for role in correspondance.get("roles", [])
    }

    assert roles == ROLES_PAR_SCOPE[scope]


def test_le_client_frontend_porte_les_scopes_metier_par_defaut() -> None:
    par_defaut, optionnels = _scopes_du_client(_clients(_realm())["frontend"])

    assert par_defaut >= SCOPES_METIER, sorted(SCOPES_METIER - par_defaut)
    assert not SCOPES_METIER & optionnels


def test_le_client_revendeur_est_confidentiel_en_client_credentials_seulement() -> None:
    clients = _clients(_realm())
    assert REVENDEUR in clients, f"client {REVENDEUR} absent du realm"
    revendeur = clients[REVENDEUR]

    assert revendeur.get("publicClient") is False
    assert revendeur.get("serviceAccountsEnabled") is True
    assert revendeur.get("standardFlowEnabled") is False
    assert revendeur.get("directAccessGrantsEnabled") is False
    assert revendeur.get("implicitFlowEnabled") is False
    assert revendeur.get("secret") == "${KEYCLOAK_REVENDEUR_SECRET}"


def test_le_client_revendeur_a_exactement_les_scopes_de_la_conception() -> None:
    clients = _clients(_realm())
    assert REVENDEUR in clients, f"client {REVENDEUR} absent du realm"
    par_defaut, optionnels = _scopes_du_client(clients[REVENDEUR])
    interdits = {"events:write", "echos:read", "echos:write"} | SCOPES_SERVICE

    assert par_defaut & SCOPES_METIER == SCOPES_REVENDEUR
    assert not interdits & par_defaut
    assert not interdits & optionnels
    assert not SCOPES_METIER & optionnels


def test_le_client_revendeur_n_a_aucun_scope_optionnel() -> None:
    # Review S4 (validation 2) : un scope optionnel (offline_access...) s'obtient en le demandant.
    clients = _clients(_realm())
    assert REVENDEUR in clients, f"client {REVENDEUR} absent du realm"
    # Seconde review (point 9) : une clé absente fait hériter des scopes optionnels du realm.
    revendeur = clients[REVENDEUR]
    assert "optionalClientScopes" in revendeur, "optionalClientScopes absent : hérite du realm"

    assert revendeur["optionalClientScopes"] == [], revendeur["optionalClientScopes"]


def test_le_compte_de_service_du_revendeur_a_le_seul_role_partner() -> None:
    comptes = {utilisateur["username"]: utilisateur for utilisateur in _realm()["users"]}
    nom = f"service-account-{REVENDEUR}"
    assert nom in comptes, f"utilisateur {nom} absent du realm"
    compte = comptes[nom]

    assert compte.get("serviceAccountClientId") == REVENDEUR
    assert set(compte.get("realmRoles", [])) & ROLES_METIER == {"partner"}


def test_le_client_services_n_a_aucun_scope_metier_d_utilisateur() -> None:
    par_defaut, optionnels = _scopes_du_client(_clients(_realm())["services"])

    assert not SCOPES_METIER & par_defaut
    assert not SCOPES_METIER & optionnels


def test_le_client_services_porte_seats_lock_et_payments_write() -> None:
    realm = _realm()
    clients = _clients(realm)
    declares = {scope["name"] for scope in realm["clientScopes"]}

    assert declares >= SCOPES_SERVICE, sorted(SCOPES_SERVICE - declares)
    assert set(clients["services"].get("defaultClientScopes", [])) >= SCOPES_SERVICE
    assert not SCOPES_SERVICE & set(realm["defaultDefaultClientScopes"])
    assert not SCOPES_SERVICE & set(realm["defaultOptionalClientScopes"])
    for scope in SCOPES_SERVICE:
        detenteurs = {
            nom
            for nom, client in clients.items()
            if scope in set().union(*_scopes_du_client(client))
        }
        assert detenteurs == {"services"}, scope


def test_l_utilisateur_partenaire_test_n_existe_plus() -> None:
    noms = {utilisateur["username"] for utilisateur in _realm()["users"]}

    assert "partenaire.test" not in noms
    assert "KEYCLOAK_MDP_PARTENAIRE" not in REALM.read_text(encoding="utf-8")


# --- BIL-003 : import fidèle du realm (CA2) ---


def test_chaque_scope_reference_par_un_client_est_declare_dans_le_realm() -> None:
    # Un scope ou un rôle inconnu est ignoré sans bruit à l'import : la config diffèrerait du JSON.
    realm = _realm()
    scopes = {scope["name"] for scope in realm["clientScopes"]}
    # default-roles-<realm> est créé par Keycloak lui-même à l'import, sans déclaration.
    roles = {role["name"] for role in realm["roles"]["realm"]} | {"default-roles-billetterie"}

    for client in realm["clients"]:
        references = set().union(*_scopes_du_client(client))
        assert references <= scopes, (client["clientId"], sorted(references - scopes))
    for correspondance in realm.get("scopeMappings", []):
        assert correspondance.get("clientScope") in scopes, correspondance
        assert set(correspondance.get("roles", [])) <= roles, correspondance
    for utilisateur in realm["users"]:
        assert set(utilisateur.get("realmRoles", [])) <= roles, utilisateur["username"]


# --- BIL-003 : secrets de test uniquement (C1) ---


def test_le_secret_du_revendeur_est_documente_vide_et_transmis_a_keycloak() -> None:
    variable = "KEYCLOAK_REVENDEUR_SECRET"
    lignes = (RACINE / ".env.example").read_text(encoding="utf-8").splitlines()

    assert f"{variable}=" in lignes, f".env.example doit documenter {variable}, valeur vide"
    for fichier in ("compose.yaml", "compose.prod.yaml"):
        compose = yaml.safe_load((RACINE / fichier).read_text(encoding="utf-8"))
        environnement = compose["services"]["keycloak"]["environment"]
        valeur = str(environnement.get(variable, ""))
        assert valeur.startswith("${" + variable + ":?"), f"{fichier} : {valeur!r}"
        assert valeur.endswith("}"), f"{fichier} : {valeur!r}"
