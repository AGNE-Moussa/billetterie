"""BIL-008, E10 (décisions Q23 et Q25) : commandes et paiements démarrent avec leur nouvelle
configuration derrière Consul et Traefik (adaptation de test_squelettes_gateway.py).

Réseau Testcontainers : Consul, Traefik avec la configuration réelle de infra/traefik/, faux
vérificateur du conftest (accepte tout jeton à la gateway), PostgreSQL 16 (bases `commandes`
et `paiements`), une migration par service lancée une fois avec son image, puis
`commandes-1`, `commandes-2` et `paiements-1`. Le service revérifie le jeton : sans jeton,
`POST /api/v1/orders` répond 401 à travers la gateway.
"""

import asyncio
import secrets
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.image import DockerImage
from testcontainers.core.network import Network

pytestmark = pytest.mark.anyio

RACINE = Path(__file__).resolve().parents[2]
IMAGE_POSTGRES = "postgres:16.10-alpine"
INSTANCES = {"commandes": ("commandes-1", "commandes-2"), "paiements": ("paiements-1",)}
DELAI_ETAPE = 120.0
DELAI_CONSTRUCTION = 600.0
DELAI_APPEL = 10.0
CONNEXION_BORNEE = {"timeout": 30, "command_timeout": 30}


@dataclass
class Plateforme:
    instances: dict[str, DockerContainer]
    migrations: dict[str, tuple[int | None, str]]


@pytest.fixture(scope="module")
def bases(reseau: Network, borne: Any, journal: Any) -> Iterator[dict[str, str]]:
    """Bases `commandes` et `paiements` sur le réseau (alias postgres), URL vue des conteneurs."""
    mot_de_passe = secrets.token_urlsafe(16)
    pg = PostgresContainer(
        IMAGE_POSTGRES, username="essai", password=mot_de_passe, dbname="commandes"
    )
    pg.with_network(reseau).with_network_aliases("postgres")
    borne("démarrage de PostgreSQL", DELAI_ETAPE, pg.start, lambda: journal(pg))
    try:
        hote = pg.get_container_host_ip().replace("localhost", "127.0.0.1")
        url_hote = f"postgresql+asyncpg://essai:{mot_de_passe}@{hote}:{pg.get_exposed_port(5432)}"

        async def creer() -> None:
            moteur = create_async_engine(
                f"{url_hote}/commandes", isolation_level="AUTOCOMMIT", connect_args=CONNEXION_BORNEE
            )
            try:
                async with moteur.connect() as connexion:
                    await connexion.execute(sa.text("CREATE DATABASE paiements"))
            finally:
                await moteur.dispose()

        asyncio.run(creer())
        yield {
            nom: f"postgresql+asyncpg://essai:{mot_de_passe}@postgres:5432/{nom}"
            for nom in INSTANCES
        }
    finally:
        borne("arrêt de PostgreSQL", DELAI_ETAPE, pg.stop, lambda: journal(pg))


def _migrer_une_fois(
    image: str, reseau: Network, url: str, borne: Any, journal: Any
) -> tuple[int | None, str]:
    migration = (
        DockerContainer(image)
        .with_command("alembic upgrade head")
        .with_env("DATABASE_URL", url)
        .with_network(reseau)
    )
    borne(
        f"démarrage de la migration ({image})",
        DELAI_ETAPE,
        migration.start,
        lambda: journal(migration),
    )
    debut = time.monotonic()
    code: int | None = None
    try:
        while time.monotonic() < debut + DELAI_ETAPE:
            enveloppe = migration.get_wrapped_container()
            enveloppe.reload()
            if enveloppe.status == "exited":
                code = int(enveloppe.attrs["State"]["ExitCode"])
                break
            time.sleep(1)
        return code, journal(migration)
    finally:
        borne(
            f"arrêt de la migration ({image})",
            DELAI_ETAPE,
            migration.stop,
            lambda: journal(migration),
        )


@pytest.fixture(scope="module")
def plateforme(
    reseau: Network,
    consul_url: str,
    gateway_url: str,
    bases: dict[str, str],
    borne: Any,
    journal: Any,
) -> Iterator[Plateforme]:
    images = {
        nom: DockerImage(
            path=str(RACINE),
            dockerfile_path=f"services/{nom}/Dockerfile",
            tag=f"billetterie/{nom}:test",
        )
        for nom in INSTANCES
    }
    instances: dict[str, DockerContainer] = {}
    migrations: dict[str, tuple[int | None, str]] = {}
    try:
        for nom, image in images.items():
            borne(
                f"construction de l'image {nom}",
                DELAI_CONSTRUCTION,
                image.build,
                lambda: "en cours",
            )
            migrations[nom] = _migrer_une_fois(str(image), reseau, bases[nom], borne, journal)
            for instance in INSTANCES[nom]:
                conteneur = (
                    DockerContainer(str(image))
                    .with_env("DATABASE_URL", bases[nom])
                    .with_env("CONSUL_URL", "http://consul:8500")
                    .with_env("INSTANCE", instance)
                    .with_network(reseau)
                    .with_network_aliases(instance)
                )
                if nom == "commandes":
                    # Configuration de la décision Q23 (secret synthétique, Keycloak absent :
                    # le jeton de service n'est demandé qu'au premier appel sortant).
                    conteneur.with_env("URL_GATEWAY", "http://traefik").with_env(
                        "SERVICES_CLIENT_SECRET", secrets.token_urlsafe(16)
                    )
                instances[instance] = conteneur
                if migrations[nom][0] == 0:
                    borne(
                        f"démarrage de {instance}",
                        DELAI_ETAPE,
                        conteneur.start,
                        lambda c=conteneur: journal(c),
                    )
        yield Plateforme(instances, migrations)
    finally:
        for nom, conteneur in instances.items():
            if conteneur._container is not None:  # noqa: SLF001 : démarré
                borne(
                    f"arrêt de {nom}", DELAI_ETAPE, conteneur.stop, lambda c=conteneur: journal(c)
                )
        for image in images.values():
            borne("suppression d'image", DELAI_ETAPE, image.remove, lambda: "en cours")


async def test_les_squelettes_demarrent_avec_la_nouvelle_configuration(
    plateforme: Plateforme, consul_url: str, gateway_url: str, journal: Any
) -> None:
    for nom, (code, texte) in plateforme.migrations.items():
        assert code == 0, f"migration de {nom} (code {code}) :\n{texte}"

    attendues = {nom: set(instances) for nom, instances in INSTANCES.items()}
    passing: dict[str, set[str]] = {}
    debut = time.monotonic()
    async with httpx.AsyncClient(base_url=consul_url, timeout=DELAI_APPEL) as consul:
        while time.monotonic() < debut + DELAI_ETAPE:
            for nom in INSTANCES:
                try:
                    entrees = (await consul.get(f"/v1/health/service/{nom}?passing=1")).json()
                except (httpx.HTTPError, ValueError):
                    entrees = []
                passing[nom] = {e["Service"]["Address"] for e in entrees}
            if passing == attendues:
                break
            await anyio.sleep(2)
    journaux = "\n".join(f"--- {n} ---\n{journal(c)}" for n, c in plateforme.instances.items())
    assert passing == attendues, f"instances passing : {passing}\n{journaux}"

    reponse = httpx.Response(404)
    debut = time.monotonic()
    async with httpx.AsyncClient(base_url=gateway_url, timeout=DELAI_APPEL) as client:
        # Traefik découvre la route après Consul : 404 tant qu'elle n'existe pas.
        while time.monotonic() < debut + DELAI_ETAPE:
            reponse = await client.post("/api/v1/orders", json={})
            if reponse.status_code != 404:
                break
            await anyio.sleep(1)

    assert reponse.status_code == 401, reponse.text
