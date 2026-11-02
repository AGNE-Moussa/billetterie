"""BIL-006, E8 (décision Q6) : places publiques et verrou protégé, de bout en bout via Traefik.

Réseau Testcontainers : Consul, Traefik avec la configuration réelle de infra/traefik/, vrai
vérificateur (image construite depuis infra/verificateur/Dockerfile) avec la valeur par défaut
de `ROUTES_PUBLIQUES` lue dans compose.yaml, PostgreSQL 16, Redis 7, image de billets
construite une seule fois pour le module, migrée par un conteneur `alembic upgrade head` puis
démarrée en `billets-1`.

Les jetons viennent de `commun.faux_jetons.EmetteurDeTest` : un petit serveur HTTP du réseau
(`jwks`) publie ses clés publiques, lues par le vérificateur et par billets.
"""

import json
import re
import secrets
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
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
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from commun.faux_jetons import EMETTEUR_TEST, EmetteurDeTest

pytestmark = pytest.mark.anyio

RACINE = Path(__file__).resolve().parents[2]
DOCKERFILE = "services/billets/Dockerfile"
CONTRAT = RACINE / "services" / "billets" / "openapi.yaml"
IMAGE_POSTGRES = "postgres:16.10-alpine"
IMAGE_REDIS = "redis:7.4.6-alpine"
IMAGE_JWKS = "hashicorp/http-echo:1.0"
INSTANCE = "billets-1"
URL_JWKS = "http://jwks:5678/"
ROUTE_PLACES = "/api/v1/seats"
ROUTE_SANTE = "/api/v1/seats/health"
DELAI_ETAPE = 120.0
DELAI_CONSTRUCTION = 600.0
DELAI_APPEL = 10.0


def _routes_publiques_du_compose() -> str:
    """Valeur par défaut de ROUTES_PUBLIQUES dans compose.yaml (décision Q6)."""
    compose: dict[str, Any] = yaml.safe_load((RACINE / "compose.yaml").read_text(encoding="utf-8"))
    valeur = str(compose["services"]["verificateur"]["environment"]["ROUTES_PUBLIQUES"])
    defaut = re.fullmatch(r"\$\{ROUTES_PUBLIQUES:-(.*)\}", valeur)
    assert defaut is not None, valeur
    return defaut.group(1)


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
        tag="billetterie/verificateur:test-billets",
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
            .with_env("ROUTES_PUBLIQUES", _routes_publiques_du_compose())
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
class Billets:
    conteneur: DockerContainer


def _migrer_une_fois(image: str, reseau: Network, url_base: str, journal: Any) -> None:
    """Comme billets-migrations dans le compose : même image, une seule fois."""
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
def billets(
    reseau: Network, consul_url: str, jwks: None, borne: Any, journal: Any
) -> Iterator[Billets]:
    """Base `billets`, Redis, image construite une fois, migration unique, instance billets-1."""
    mot_de_passe = secrets.token_urlsafe(16)
    pg = PostgresContainer(
        IMAGE_POSTGRES, username="billets", password=mot_de_passe, dbname="billets"
    )
    pg.with_network(reseau).with_network_aliases("postgres-billets")
    url_base = f"postgresql+asyncpg://billets:{mot_de_passe}@postgres-billets:5432/billets"
    redis = (
        DockerContainer(IMAGE_REDIS)
        .with_network(reseau)
        .with_network_aliases("redis")
        .waiting_for(LogMessageWaitStrategy("Ready to accept connections"))
    )
    image = DockerImage(
        path=str(RACINE), dockerfile_path=DOCKERFILE, tag="billetterie/billets:test-gateway"
    )
    with pg, redis:
        borne(
            "construction de l'image billetterie/billets:test-gateway",
            DELAI_CONSTRUCTION,
            image.build,
            lambda: "construction docker toujours en cours",
        )
        try:
            _migrer_une_fois(str(image), reseau, url_base, journal)
            instance = (
                DockerContainer(str(image))
                .with_env("DATABASE_URL", url_base)
                .with_env("REDIS_URL", "redis://redis:6379/0")
                .with_env("CONSUL_URL", "http://consul:8500")
                .with_env("INSTANCE", INSTANCE)
                .with_env("JWKS_URL", URL_JWKS)
                .with_network(reseau)
                .with_network_aliases(INSTANCE)
            )
            with instance:
                yield Billets(instance)
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
    client: httpx.AsyncClient, service: dict[str, str], billets: Billets, journal: Any
) -> None:
    """Attend que Traefik ait découvert la santé de billets (404 tant qu'elle n'existe pas)."""
    limite = time.monotonic() + DELAI_ETAPE
    dernier = "aucune réponse"
    while time.monotonic() < limite:
        try:
            reponse = await client.get(ROUTE_SANTE, headers=service)
        except httpx.HTTPError as erreur:
            dernier = repr(erreur)
        else:
            if reponse.status_code == 200:
                return
            dernier = f"{reponse.status_code} {reponse.text[:200]!r}"
        await anyio.sleep(1)
    raise AssertionError(
        f"santé de billets jamais servie par Traefik ; dernière réponse : {dernier} ;"
        f" journal de {INSTANCE} :\n{journal(billets.conteneur)}"
    )


async def test_les_places_repondent_sans_jeton_et_le_verrou_exige_un_jeton_via_la_gateway(
    gateway_url: str,
    billets: Billets,
    emetteur: EmetteurDeTest,
    composants: dict[str, Any],
    journal: Any,
) -> None:
    service = emetteur.entetes(sujet="service-test", client="services", scopes=["seats:lock"])
    async with httpx.AsyncClient(base_url=gateway_url, timeout=DELAI_APPEL) as client:
        await _attendre_route(client, service, billets, journal)

        places = await client.get(ROUTE_PLACES, params={"seance_id": str(uuid.uuid4())})
        sante = await client.get(ROUTE_SANTE)
        verrou = await client.put(
            f"{ROUTE_PLACES}/{uuid.uuid4()}/lock",
            json={"seance_id": str(uuid.uuid4()), "commande_id": str(uuid.uuid4())},
        )

    assert places.status_code == 200, places.text
    assert _erreurs_schema(places.json(), "PlacePage", composants) == []
    assert places.headers.get("X-Correlation-Id")
    assert sante.status_code == 200, sante.text
    assert sante.json() == {"statut": "ok"}
    assert sante.headers.get("X-Correlation-Id")
    assert verrou.status_code == 401, verrou.text
    assert verrou.headers["content-type"].startswith("application/problem+json")
    assert verrou.headers.get("X-Correlation-Id")
