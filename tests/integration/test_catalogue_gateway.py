"""BIL-004, CA3 (décisions Q3, Q4, Q19) : catalogue de bout en bout derrière Traefik.

Réseau Testcontainers : Consul, Traefik avec la configuration réelle de infra/traefik/, vrai
vérificateur (image construite depuis infra/verificateur/Dockerfile) avec les routes publiques
retenues en Q3, PostgreSQL 16, image de catalogue construite une seule fois pour le module,
migrée par un conteneur `alembic upgrade head` puis démarrée en `catalogue-1`.

Les jetons viennent de `commun.faux_jetons.EmetteurDeTest` : un petit serveur HTTP du réseau
(`jwks`) publie ses clés publiques, lues par le vérificateur et par catalogue (même émetteur,
même audience que le realm).
"""

import json
import secrets
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
import yaml
from jsonschema import Draft202012Validator
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.image import DockerImage
from testcontainers.core.network import Network

from commun.faux_jetons import EMETTEUR_TEST, EmetteurDeTest

pytestmark = pytest.mark.anyio

RACINE = Path(__file__).resolve().parents[2]
DOCKERFILE = "services/catalogue/Dockerfile"
CONTRAT = RACINE / "services" / "catalogue" / "openapi.yaml"
IMAGE_POSTGRES = "postgres:16.10-alpine"
IMAGE_JWKS = "hashicorp/http-echo:1.0"
INSTANCE = "catalogue-1"
URL_JWKS = "http://jwks:5678/"
# Décision Q3 (option a) : valeur par défaut de ROUTES_PUBLIQUES dans compose.yaml.
ROUTES_PUBLIQUES = "GET /api/v1/events,GET /api/v1/venues,GET /api/v1/shows"
DELAI_ETAPE = 120.0
DELAI_CONSTRUCTION = 600.0
DELAI_APPEL = 10.0

EVENEMENT = {"nom": "Concert de test", "description": "Description synthétique"}
LIEU = {"nom": "Salle de test", "adresse": "1 rue de l'Exemple", "ville": "Villetest"}


@pytest.fixture(scope="module")
def emetteur() -> EmetteurDeTest:
    return EmetteurDeTest()


@pytest.fixture(scope="module")
def jwks(reseau: Network, emetteur: EmetteurDeTest) -> Iterator[None]:
    """Serveur HTTP qui renvoie le JWKS de l'émetteur de test sur toute route."""
    conteneur = (
        DockerContainer(IMAGE_JWKS)
        .with_command(["-listen=:5678", f"-text={json.dumps(emetteur.jwks())}"])
        .with_network(reseau)
        .with_network_aliases("jwks")
    )
    with conteneur:
        yield


def _attendre_sante(url: str, delai: float = 60.0) -> None:
    limite = time.monotonic() + delai
    while time.monotonic() < limite:
        try:
            if httpx.get(url, timeout=2.0).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise AssertionError(f"{url} ne répond pas en {delai:.0f} s")


@pytest.fixture(scope="module")
def verificateur(reseau: Network, jwks: None, borne: Any, url_hote: Any) -> Iterator[None]:
    """Remplace le faux vérificateur du conftest par l'image construite depuis le dépôt."""
    image = DockerImage(
        path=str(RACINE),
        dockerfile_path="infra/verificateur/Dockerfile",
        tag="billetterie/verificateur:test-catalogue",
    )
    borne(
        "construction de l'image du vérificateur",
        DELAI_CONSTRUCTION,
        image.build,
        lambda: "construction docker toujours en cours",
    )
    try:
        conteneur = (
            DockerContainer(str(image))
            .with_env("JWT_EMETTEUR", EMETTEUR_TEST)
            .with_env("JWKS_URL", URL_JWKS)
            .with_env("ROUTES_PUBLIQUES", ROUTES_PUBLIQUES)
            .with_network(reseau)
            .with_network_aliases("verificateur")
            .with_exposed_ports(8000)
        )
        with conteneur:
            _attendre_sante(f"{url_hote(conteneur, 8000)}/health")
            yield
    finally:
        image.remove()


@dataclass
class Catalogue:
    conteneur: DockerContainer


def _migrer_une_fois(image: str, reseau: Network, url_base: str, journal: Any) -> None:
    """Comme catalogue-migrations dans le compose : même image, une seule fois."""
    migration = (
        DockerContainer(image)
        .with_command("alembic upgrade head")
        .with_env("DATABASE_URL", url_base)
        .with_network(reseau)
    )
    with migration:
        limite = time.monotonic() + DELAI_ETAPE
        while time.monotonic() < limite:
            enveloppe = migration.get_wrapped_container()
            enveloppe.reload()
            if enveloppe.status == "exited":
                code = int(enveloppe.attrs["State"]["ExitCode"])
                assert code == 0, f"migration en échec ({code}) :\n{journal(migration)}"
                return
            time.sleep(1)
        raise AssertionError(f"migration toujours en cours :\n{journal(migration)}")


@pytest.fixture(scope="module")
def catalogue(
    reseau: Network, consul_url: str, jwks: None, borne: Any, journal: Any
) -> Iterator[Catalogue]:
    """Base `catalogue`, image construite une fois, migration unique, instance catalogue-1."""
    mot_de_passe = secrets.token_urlsafe(16)
    pg = PostgresContainer(
        IMAGE_POSTGRES, username="catalogue", password=mot_de_passe, dbname="catalogue"
    )
    pg.with_network(reseau).with_network_aliases("postgres-catalogue")
    url_base = f"postgresql+asyncpg://catalogue:{mot_de_passe}@postgres-catalogue:5432/catalogue"
    image = DockerImage(
        path=str(RACINE), dockerfile_path=DOCKERFILE, tag="billetterie/catalogue:test"
    )
    with pg:
        borne(
            "construction de l'image billetterie/catalogue:test",
            DELAI_CONSTRUCTION,
            image.build,
            lambda: "construction docker toujours en cours",
        )
        try:
            _migrer_une_fois(str(image), reseau, url_base, journal)
            instance = (
                DockerContainer(str(image))
                .with_env("DATABASE_URL", url_base)
                .with_env("CONSUL_URL", "http://consul:8500")
                .with_env("INSTANCE", INSTANCE)
                .with_env("JWKS_URL", URL_JWKS)
                .with_network(reseau)
                .with_network_aliases(INSTANCE)
            )
            with instance:
                yield Catalogue(instance)
        finally:
            image.remove()


@pytest.fixture(scope="module")
def composants() -> dict[str, Any]:
    contrat: dict[str, Any] = yaml.safe_load(CONTRAT.read_text(encoding="utf-8"))
    return contrat["components"]  # type: ignore[no-any-return]


def _erreurs_schema(corps: Any, schema: str, composants: dict[str, Any]) -> list[str]:
    validateur = Draft202012Validator(
        {"$ref": f"#/components/schemas/{schema}", "components": composants}
    )
    return [f"{list(e.absolute_path)} : {e.message}" for e in validateur.iter_errors(corps)]


async def _attendre_route(
    client: httpx.AsyncClient, admin: dict[str, str], catalogue: Catalogue, journal: Any
) -> None:
    """Attend que Traefik ait découvert le routeur de catalogue (404 tant qu'il n'existe pas)."""
    limite = time.monotonic() + DELAI_ETAPE
    dernier = "aucune réponse"
    while time.monotonic() < limite:
        try:
            reponse = await client.get("/api/v1/events", headers=admin)
        except httpx.HTTPError as erreur:
            dernier = repr(erreur)
        else:
            if reponse.status_code != 404:
                return
            dernier = f"{reponse.status_code} {reponse.text[:200]!r}"
        await anyio.sleep(1)
    raise AssertionError(
        f"routeur de catalogue jamais découvert par Traefik ; dernière réponse : {dernier} ;"
        f" journal de {INSTANCE} :\n{journal(catalogue.conteneur)}"
    )


def _appels_recus(conteneur: DockerContainer, correlation: str) -> int:
    """Lignes du journal d'accès d'uvicorn (JSON) portant cette corrélation."""
    sortie, erreurs = conteneur.get_logs()
    total = 0
    for ligne in (sortie + erreurs).decode("utf-8", errors="replace").splitlines():
        try:
            entree = json.loads(ligne)
        except json.JSONDecodeError:
            continue
        if (
            entree.get("journal") == "uvicorn.access"
            and entree.get("correlation_id") == correlation
        ):
            total += 1
    return total


async def test_une_lecture_du_catalogue_repond_sans_jeton_via_la_gateway(
    gateway_url: str,
    catalogue: Catalogue,
    emetteur: EmetteurDeTest,
    composants: dict[str, Any],
    journal: Any,
) -> None:
    admin = emetteur.entetes(roles=["admin"], scopes=["events:read", "events:write"])
    async with httpx.AsyncClient(base_url=gateway_url, timeout=DELAI_APPEL) as client:
        await _attendre_route(client, admin, catalogue, journal)

        evenements = await client.get("/api/v1/events")
        lieux = await client.get("/api/v1/venues")
        assert evenements.status_code == 200, evenements.text
        assert lieux.status_code == 200, lieux.text
        assert _erreurs_schema(evenements.json(), "EvenementPage", composants) == []
        assert _erreurs_schema(lieux.json(), "LieuPage", composants) == []
        assert evenements.headers.get("X-Correlation-Id")
        assert lieux.headers.get("X-Correlation-Id")

        evenement = await client.post("/api/v1/events", json=EVENEMENT, headers=admin)
        lieu = await client.post("/api/v1/venues", json=LIEU, headers=admin)
        assert evenement.status_code == 201, evenement.text
        assert lieu.status_code == 201, lieu.text
        debut = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        corps_seance = {
            "lieu_id": lieu.json()["id"],
            "debut": debut,
            "categories": [
                {"nom": "Fosse", "prix": 4500, "rangs": [{"rang": "A", "nombre_places": 10}]}
            ],
        }
        seance = await client.post(
            f"/api/v1/events/{evenement.json()['id']}/shows", json=corps_seance, headers=admin
        )
        assert seance.status_code == 201, seance.text

        lue = await client.get(f"/api/v1/shows/{seance.json()['id']}")

    assert lue.status_code == 200, lue.text
    assert _erreurs_schema(lue.json(), "Seance", composants) == []
    assert lue.headers.get("X-Correlation-Id")


async def test_une_creation_sans_jeton_est_refusee_par_la_gateway(
    gateway_url: str, catalogue: Catalogue, emetteur: EmetteurDeTest, journal: Any
) -> None:
    admin = emetteur.entetes(roles=["admin"], scopes=["events:read", "events:write"])
    correlation = f"correlation-bil-004-gateway-{secrets.token_hex(4)}"
    async with httpx.AsyncClient(base_url=gateway_url, timeout=DELAI_APPEL) as client:
        await _attendre_route(client, admin, catalogue, journal)

        reponse = await client.post(
            "/api/v1/events", json=EVENEMENT, headers={"X-Correlation-Id": correlation}
        )

    assert reponse.status_code == 401, reponse.text
    assert reponse.headers["content-type"].startswith("application/problem+json")
    assert reponse.headers.get("WWW-Authenticate", "").startswith("Bearer")
    await anyio.sleep(1)  # laisse le journal d'accès s'écrire, si l'appel avait atteint le service
    assert _appels_recus(catalogue.conteneur, correlation) == 0


async def test_une_creation_avec_le_jeton_admin_passe_par_la_gateway(
    gateway_url: str, catalogue: Catalogue, emetteur: EmetteurDeTest, journal: Any
) -> None:
    admin = emetteur.entetes(roles=["admin"], scopes=["events:read", "events:write"])
    async with httpx.AsyncClient(base_url=gateway_url, timeout=DELAI_APPEL) as client:
        await _attendre_route(client, admin, catalogue, journal)

        evenement = await client.post("/api/v1/events", json=EVENEMENT, headers=admin)
        lieu = await client.post("/api/v1/venues", json=LIEU, headers=admin)
        assert evenement.status_code == 201, evenement.text
        assert lieu.status_code == 201, lieu.text
        relu = await client.get(f"/api/v1/events/{evenement.json()['id']}", headers=admin)

    assert relu.status_code == 200, relu.text
    assert relu.json()["id"] == evenement.json()["id"]
    assert relu.json()["nom"] == "Concert de test"
