"""BIL-012, CA3 (décisions Q1, Q2, Q6) et contrainte « Client Credentials uniquement » : vrai
Traefik (configuration réelle de infra/traefik/), vrai vérificateur construit depuis le dépôt,
Keycloak qui importe le realm versionné, whoami annoncé dans Consul.

Hôte partenaires : `partenaires.localhost` (question 1 du plan), envoyé dans l'en-tête `Host`.
Chaîne `standard@file` sur `/verifier`, chaîne `partenaires@file` sur `/verifier/partenaires`.
"""

import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import anyio
import httpx
import jwt
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.image import DockerImage
from testcontainers.core.network import Network

from commun.registre import (
    desenregistrer,
    enregistrer,
    tags_partenaires_traefik,
    tags_traefik,
)

pytestmark = pytest.mark.anyio

RACINE = Path(__file__).resolve().parents[2]
IMAGE_KEYCLOAK = "quay.io/keycloak/keycloak:26.4.1"
EMETTEUR = "http://localhost/auth/realms/billetterie"
CERTS = "http://keycloak:8080/auth/realms/billetterie/protocol/openid-connect/certs"
OIDC = "/auth/realms/billetterie/protocol/openid-connect"
PORT_WHOAMI = 80
HOTE_PARTENAIRES = "partenaires.localhost"
REVENDEUR = "revendeur-test"
AUDIENCE = "billetterie-api"
REDIRECTION = "http://localhost/rappel"
RAFALE = 30
REPOS = 3.0


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


async def _jeton(keycloak_url: str, client_id: str, secret: str) -> str:
    async with httpx.AsyncClient() as client:
        reponse = await client.post(
            f"{keycloak_url}{OIDC}/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": secret,
            },
        )
    assert reponse.status_code == 200, f"jeton {client_id} : {reponse.text}"
    jeton: str = reponse.json()["access_token"]
    return jeton


async def _jeton_revendeur(keycloak_url: str, secrets_realm: dict[str, str]) -> str:
    return await _jeton(keycloak_url, REVENDEUR, secrets_realm["KEYCLOAK_REVENDEUR_SECRET"])


def _entete_recu(reponse: httpx.Response, nom: str) -> str | None:
    """Valeur d'un en-tête reçu par whoami (il les recopie dans sa réponse)."""
    for ligne in reponse.text.splitlines():
        cle, _, valeur = ligne.partition(": ")
        if cle.lower() == nom.lower():
            return valeur.strip()
    return None


async def _exposer(service: str, instances: list[str], *, partenaires: bool) -> list[str]:
    """Annonce whoami sous `/api/v1/<service>` : routeur standard, plus le routeur des
    revendeurs sur l'hôte partenaires si `partenaires`."""
    tags = tags_traefik(service, service)
    if partenaires:
        tags += tags_partenaires_traefik(service, service, hote=HOTE_PARTENAIRES)
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


def _partenaires(jeton: str) -> dict[str, str]:
    return {"Host": HOTE_PARTENAIRES, "Authorization": f"Bearer {jeton}"}


async def _rafale(client: httpx.AsyncClient, route: str, entetes: dict[str, str]) -> list[Any]:
    """`RAFALE` appels simultanés, après `REPOS` secondes sans appel (seau rempli)."""
    await anyio.sleep(REPOS)
    reponses: list[httpx.Response] = []

    async def appeler() -> None:
        reponses.append(await client.get(route, headers=entetes))

    async with anyio.create_task_group() as groupe:
        for _ in range(RAFALE):
            groupe.start_soon(appeler)
    return reponses


# --- CA3 : quota de la chaîne partenaires ------------------------------------------------------


async def test_au_dela_du_quota_le_revendeur_recoit_429_sur_l_hote_partenaires(
    gateway_url: str,
    instances_whoami: list[str],
    keycloak_url: str,
    secrets_realm: dict[str, str],
) -> None:
    identifiants = await _exposer("quotas", instances_whoami, partenaires=True)
    route = "/api/v1/quotas"
    entetes = _partenaires(await _jeton_revendeur(keycloak_url, secrets_realm))
    try:
        async with httpx.AsyncClient(base_url=gateway_url) as client:
            await _attendre_route(client, route, entetes)

            reponses = await _rafale(client, route, entetes)
    finally:
        for identifiant in identifiants:
            await desenregistrer(identifiant)

    statuts = sorted(r.status_code for r in reponses)
    assert set(statuts) == {200, 429}, statuts
    passees = [r for r in reponses if r.status_code == 200]
    assert all(_entete_recu(r, "Name") in instances_whoami for r in passees)
    for refusee in (r for r in reponses if r.status_code == 429):
        assert not refusee.headers.get("content-type", "").startswith("application/problem+json")


async def test_le_429_partenaire_indique_quand_reessayer(
    gateway_url: str,
    instances_whoami: list[str],
    keycloak_url: str,
    secrets_realm: dict[str, str],
) -> None:
    identifiants = await _exposer("delais", instances_whoami, partenaires=True)
    route = "/api/v1/delais"
    entetes = _partenaires(await _jeton_revendeur(keycloak_url, secrets_realm))
    try:
        async with httpx.AsyncClient(base_url=gateway_url) as client:
            await _attendre_route(client, route, entetes)

            reponses = await _rafale(client, route, entetes)
    finally:
        for identifiant in identifiants:
            await desenregistrer(identifiant)

    refusees = [r for r in reponses if r.status_code == 429]
    assert refusees, sorted(r.status_code for r in reponses)
    assert all(r.headers.get("Retry-After") for r in refusees), [dict(r.headers) for r in refusees]


async def test_le_quota_d_un_revendeur_ne_bloque_pas_un_autre_jeton(
    gateway_url: str,
    instances_whoami: list[str],
    keycloak_url: str,
    secrets_realm: dict[str, str],
) -> None:
    identifiants = await _exposer("seaux", instances_whoami, partenaires=True)
    route = "/api/v1/seaux"
    premier = await _jeton_revendeur(keycloak_url, secrets_realm)
    second = await _jeton_revendeur(keycloak_url, secrets_realm)
    assert premier != second
    try:
        async with httpx.AsyncClient(base_url=gateway_url) as client:
            await _attendre_route(client, route, _partenaires(premier))
            reponses = await _rafale(client, route, _partenaires(premier))
            assert 429 in {r.status_code for r in reponses}, "quota du premier jeton non atteint"

            autre = await client.get(route, headers=_partenaires(second))
    finally:
        for identifiant in identifiants:
            await desenregistrer(identifiant)

    assert autre.status_code == 200, autre.text
    assert _entete_recu(autre, "Name") in instances_whoami


# --- CA3 : refus de rôle par chaîne (Q2, question 2 du plan) -----------------------------------


async def test_le_jeton_du_revendeur_est_refuse_sur_l_hote_standard(
    gateway_url: str,
    instances_whoami: list[str],
    keycloak_url: str,
    secrets_realm: dict[str, str],
) -> None:
    # Seul le routeur standard est annoncé : la requête passe par la chaîne standard@file.
    identifiants = await _exposer("standards", instances_whoami, partenaires=False)
    route = "/api/v1/standards"
    entetes = {"Authorization": f"Bearer {await _jeton_revendeur(keycloak_url, secrets_realm)}"}
    try:
        async with httpx.AsyncClient(base_url=gateway_url) as client:
            await _attendre_route(client, route, entetes)

            reponse = await client.get(route, headers=entetes)
    finally:
        for identifiant in identifiants:
            await desenregistrer(identifiant)

    assert reponse.status_code == 403, reponse.text
    assert reponse.headers["content-type"].startswith("application/problem+json")
    assert reponse.json()["code"] == "ROLE_MANQUANT"
    assert _entete_recu(reponse, "Name") is None


async def test_un_jeton_sans_role_partner_est_refuse_sur_l_hote_partenaires(
    gateway_url: str,
    instances_whoami: list[str],
    keycloak_url: str,
    secrets_realm: dict[str, str],
) -> None:
    identifiants = await _exposer("intrus", instances_whoami, partenaires=True)
    route = "/api/v1/intrus"
    jeton = await _jeton(keycloak_url, "services", secrets_realm["KEYCLOAK_SERVICES_SECRET"])
    entetes = _partenaires(jeton)
    try:
        async with httpx.AsyncClient(base_url=gateway_url) as client:
            await _attendre_route(client, route, entetes)

            reponse = await client.get(route, headers=entetes)
    finally:
        for identifiant in identifiants:
            await desenregistrer(identifiant)

    assert reponse.status_code == 403, reponse.text
    assert reponse.headers["content-type"].startswith("application/problem+json")
    assert reponse.json()["code"] == "ROLE_MANQUANT"
    assert _entete_recu(reponse, "Name") is None


# --- Contrainte « Flux Client Credentials uniquement » -----------------------------------------


async def test_le_revendeur_obtient_un_jeton_partner_par_client_credentials(
    keycloak_url: str, secrets_realm: dict[str, str]
) -> None:
    jeton = await _jeton_revendeur(keycloak_url, secrets_realm)

    claims = jwt.decode(jeton, options={"verify_signature": False})
    assert "partner" in claims["realm_access"]["roles"], claims
    scopes_metier = {s for s in claims["scope"].split() if ":" in s}
    assert scopes_metier == {"events:read", "orders:read", "orders:write", "tickets:read"}
    assert claims["azp"] == REVENDEUR
    audiences = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
    assert AUDIENCE in audiences, claims


async def test_le_revendeur_ne_peut_obtenir_de_jeton_ni_par_mot_de_passe_ni_par_code(
    keycloak_url: str, secrets_realm: dict[str, str]
) -> None:
    async with httpx.AsyncClient(base_url=keycloak_url) as client:
        mot_de_passe = await client.post(
            f"{OIDC}/token",
            data={
                "grant_type": "password",
                "client_id": REVENDEUR,
                "client_secret": secrets_realm["KEYCLOAK_REVENDEUR_SECRET"],
                "username": "client.test",
                "password": secrets_realm["KEYCLOAK_MDP_CLIENT"],
            },
        )
        code = await client.get(
            f"{OIDC}/auth",
            params={
                "client_id": REVENDEUR,
                "response_type": "code",
                "redirect_uri": REDIRECTION,
                "scope": "openid",
                "state": "etat",
            },
        )

    assert mot_de_passe.status_code in {400, 401}, mot_de_passe.text
    assert mot_de_passe.json()["error"] == "unauthorized_client", mot_de_passe.text
    assert "access_token" not in mot_de_passe.json()
    assert 'id="kc-form-login"' not in code.text
    assert code.status_code in {302, 400}, code.status_code
    if code.status_code == 302:
        assert "error=unauthorized_client" in code.headers["location"]
        assert "code=" not in code.headers["location"].replace("error=", "")
