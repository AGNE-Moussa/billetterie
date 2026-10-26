"""BIL-001 : chaque squelette sur sa vraie base PostgreSQL et dans un vrai Consul.

Une base jetable par service (utilisateur et base `<nom>`, mot de passe généré), migrée par
le `alembic.ini` du service ; jamais de simulacre de la base. Les tests à argument `squelette`
sont paramétrés sur la table SERVICES du conftest.

Chaque attente a une échéance mesurée (time.monotonic) et échoue par une assertion qui nomme
l'étape et le dernier état observé : pytest-timeout n'est pas dans le projet.
"""

import asyncio
import importlib
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from commun.faux_jetons import EmetteurDeTest

pytestmark = pytest.mark.anyio

RACINE = Path(__file__).resolve().parents[2]
IMAGE_POSTGRES = "postgres:16.10-alpine"
REVISION_INITIALE = "0001"
# Échéance d'une étape (démarrage, migration, lifespan, Consul) : large pour un poste lent.
DELAI_ETAPE = 120.0
# Premier check Consul : étalé par l'agent sur son intervalle (10 s).
DELAI_PREMIER_CHECK = 60.0
DELAI_OBSERVATION = 10.0
# Requêtes de lecture du test : asyncpg n'a aucun délai par défaut une fois connecté.
CONNEXION_BORNEE = {"timeout": 30, "command_timeout": 30}

REQUETE_VERSIONS = "SELECT version_num FROM alembic_version"
Observation = Callable[[], Awaitable[str]]
Alembic = Callable[[str, str], Awaitable[None]]


async def _observer(observe: Observation | None) -> str:
    if observe is None:
        return "(aucune observation)"
    try:
        with anyio.fail_after(DELAI_OBSERVATION):
            return await observe()
    except Exception as erreur:  # noqa: BLE001 : diagnostic seulement
        return f"(observation impossible : {erreur!r})"


async def _borne[T](
    etape: str,
    attente: Awaitable[T],
    observe: Observation | None = None,
    delai: float = DELAI_ETAPE,
) -> T:
    """Attend `attente` au plus `delai` secondes, sinon AssertionError qui nomme l'étape."""
    debut = time.monotonic()
    with anyio.move_on_after(delai):
        return await attente
    duree = time.monotonic() - debut
    raise AssertionError(
        f"{etape} : échéance de {delai:.0f} s dépassée ({duree:.0f} s mesurées) ; "
        f"dernier état observé : {await _observer(observe)}"
    )


@pytest.fixture(scope="module")
def database_url(squelette: Any, borne: Any, journal: Any) -> Iterator[str]:
    """Base `<nom>` jetable, propre au service, non migrée."""
    nom = squelette.nom
    mot_de_passe = secrets.token_urlsafe(16)
    pg = PostgresContainer(IMAGE_POSTGRES, username=nom, password=mot_de_passe, dbname=nom)
    borne(f"démarrage de PostgreSQL ({nom})", DELAI_ETAPE, pg.start, lambda: journal(pg))
    try:
        # Sous Windows, « localhost » passe d'abord par IPv6 et Docker Desktop coupe la connexion.
        hote = pg.get_container_host_ip().replace("localhost", "127.0.0.1")
        yield f"postgresql+asyncpg://{nom}:{mot_de_passe}@{hote}:{pg.get_exposed_port(5432)}/{nom}"
    finally:
        borne(f"arrêt de PostgreSQL ({nom})", DELAI_ETAPE, pg.stop, lambda: journal(pg))


def _alembic(squelette: Any) -> Config:
    ini = RACINE / "services" / squelette.nom / "alembic.ini"
    assert ini.is_file(), f"{ini.relative_to(RACINE)} absent : aucune migration à appliquer"
    return Config(str(ini))


async def _lire(database_url: str, requete: str) -> list[Any]:
    moteur = create_async_engine(database_url, connect_args=CONNEXION_BORNEE)
    try:
        async with moteur.connect() as connexion:
            return [ligne[0] for ligne in await connexion.execute(sa.text(requete))]
    finally:
        await moteur.dispose()


async def _versions(database_url: str) -> list[str]:
    return await _borne(
        "lecture de alembic_version",
        _lire(database_url, REQUETE_VERSIONS),
    )


async def _tables_publiques(database_url: str) -> set[str]:
    tables = await _borne(
        "lecture des tables du schéma public",
        _lire(
            database_url,
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'",
        ),
    )
    return set(tables)


@pytest.fixture
def alembic(
    squelette: Any, database_url: str, monkeypatch: pytest.MonkeyPatch, borne: Any
) -> Alembic:
    """Lance `alembic <commande> <cible>` avec le alembic.ini du service, sur sa base.

    La commande tourne dans un fil démon borné (conftest : executer_borne) : son env.py lance
    sa propre boucle (asyncio.run), et un fil bloqué (requête asyncpg sans délai, relais de
    ports de Docker Desktop) est abandonné au lieu de retenir le test indéfiniment.
    """

    def etat_de_la_base() -> str:
        try:
            return f"alembic_version = {asyncio.run(_lire(database_url, REQUETE_VERSIONS))}"
        except Exception as erreur:  # noqa: BLE001 : diagnostic seulement
            return f"alembic_version illisible : {erreur!r}"

    async def executer(nom_commande: str, cible: str) -> None:
        config = _alembic(squelette)
        monkeypatch.setenv("DATABASE_URL", database_url)
        commande = getattr(command, nom_commande)
        await anyio.to_thread.run_sync(
            borne,
            f"Alembic {nom_commande} {cible} ({squelette.nom})",
            DELAI_ETAPE,
            lambda: commande(config, cible),
            etat_de_la_base,
            abandon_on_cancel=True,
        )

    return executer


def _creer_app(squelette: Any, database_url: str, **reglages: Any) -> Any:
    principal = importlib.import_module(f"{squelette.nom}.principal")
    config = importlib.import_module(f"{squelette.nom}.config")
    return principal.creer_app(
        config.Parametres(database_url=database_url, **reglages),
        verificateur_jetons=EmetteurDeTest().verificateur(),
    )


@pytest.fixture
async def client_sans_consul(squelette: Any, database_url: str) -> AsyncIterator[httpx.AsyncClient]:
    app = _creer_app(squelette, database_url, instance=f"{squelette.nom}-test", consul_actif=False)
    async with AsyncExitStack() as pile:
        await _borne(
            f"démarrage du lifespan ({squelette.nom}, sans Consul)",
            pile.enter_async_context(app.router.lifespan_context(app)),
        )
        transport = httpx.ASGITransport(app=app)
        client = await pile.enter_async_context(
            httpx.AsyncClient(transport=transport, base_url="http://test")
        )
        yield client
        await _borne(f"arrêt du lifespan ({squelette.nom}, sans Consul)", pile.aclose())


async def test_la_migration_initiale_s_applique_sur_la_base_du_service(
    database_url: str, alembic: Alembic
) -> None:
    await alembic("upgrade", "head")

    assert await _versions(database_url) == [REVISION_INITIALE]
    assert await _tables_publiques(database_url) == {"alembic_version"}


async def test_la_migration_initiale_se_rejoue_sans_effet(
    database_url: str, alembic: Alembic
) -> None:
    await alembic("upgrade", "head")
    # Comme à chaque make up : le conteneur de migrations repasse sur une base à jour.
    await alembic("upgrade", "head")

    assert await _versions(database_url) == [REVISION_INITIALE]
    assert await _tables_publiques(database_url) == {"alembic_version"}


async def test_la_migration_initiale_se_defait(database_url: str, alembic: Alembic) -> None:
    await alembic("upgrade", "head")

    await alembic("downgrade", "base")
    assert await _versions(database_url) == []

    await alembic("upgrade", "head")
    assert await _versions(database_url) == [REVISION_INITIALE]


async def test_la_sante_lit_la_vraie_base_du_service(
    alembic: Alembic, client_sans_consul: httpx.AsyncClient
) -> None:
    await alembic("upgrade", "head")

    reponse = await _borne("GET /health", client_sans_consul.get("/health"))

    assert reponse.status_code == 200, reponse.text
    assert reponse.json() == {"statut": "ok"}


def _routeurs(tags: list[str]) -> dict[str, dict[str, str]]:
    """Tags Traefik regroupés par routeur : {routeur: {rule, entrypoints, middlewares}}."""
    routeurs: dict[str, dict[str, str]] = {}
    for tag in tags:
        cle, _, valeur = tag.partition("=")
        morceaux = cle.split(".")
        if morceaux[:3] == ["traefik", "http", "routers"] and len(morceaux) == 5:
            routeurs.setdefault(morceaux[3], {})[morceaux[4].lower()] = valeur
    return routeurs


def _termes_de_regle(regle: str) -> list[str]:
    """Conditions d'une règle Traefik combinées en ET ; une règle avec `||` reste entière."""
    if "||" in regle:
        return [regle.strip()]
    return [terme.strip() for terme in regle.split("&&")]


def _middlewares_replace_path(tags: list[str], chemin: str) -> set[str]:
    """Noms des middlewares Traefik déclarés en tags qui réécrivent le chemin en `chemin`."""
    noms = set()
    for tag in tags:
        cle, _, valeur = tag.partition("=")
        morceaux = cle.split(".")
        if (
            morceaux[:3] == ["traefik", "http", "middlewares"]
            and [m.lower() for m in morceaux[4:]] == ["replacepath", "path"]
            and valeur == chemin
        ):
            noms.add(morceaux[3])
    return noms


async def _consul_json(consul: httpx.AsyncClient, chemin: str) -> Any:
    """Lecture de l'API de l'agent Consul ; une erreur ou un statut inattendu fait échouer."""

    async def lire() -> Any:
        try:
            reponse = await consul.get(chemin)
        except httpx.HTTPError as erreur:
            raise AssertionError(f"Consul {chemin} injoignable : {erreur!r}") from erreur
        assert reponse.status_code == 200, f"Consul {chemin} : {reponse.status_code} {reponse.text}"
        return reponse.json()

    return await _borne(f"interrogation de Consul {chemin}", lire())


async def _checks_executes(
    consul: httpx.AsyncClient, nom: str, delai: float = DELAI_PREMIER_CHECK
) -> dict[str, Any]:
    """Checks de l'agent, une fois celui du service exécuté au moins une fois (sortie non vide).

    Consul étale la première exécution sur l'intervalle du check (10 s).
    """
    debut = time.monotonic()
    limite = debut + delai
    checks: dict[str, Any] = {}
    derniere_erreur: str | None = None
    while time.monotonic() < limite:
        try:
            reponse = await consul.get("/v1/agent/checks")
            checks = reponse.json()
            derniere_erreur = None
        except (httpx.HTTPError, ValueError) as erreur:
            derniere_erreur = repr(erreur)
        else:
            if any(c["ServiceName"] == nom and c["Output"] for c in checks.values()):
                return checks
        await anyio.sleep(1)
    du_service = [
        {"Status": c.get("Status"), "Output": c.get("Output")}
        for c in checks.values()
        if c.get("ServiceName") == nom
    ]
    raise AssertionError(
        f"premier check Consul de {nom} : échéance de {delai:.0f} s dépassée "
        f"({time.monotonic() - debut:.0f} s mesurées) ; dernier état observé : {du_service}"
        + (f", dernière erreur : {derniere_erreur}" if derniere_erreur else "")
    )


async def test_chaque_service_s_inscrit_dans_consul_avec_ses_tags_son_check_et_ses_metriques(
    squelette: Any,
    database_url: str,
    consul_url: str,
    monkeypatch: pytest.MonkeyPatch,
    alembic: Alembic,
) -> None:
    await alembic("upgrade", "head")
    monkeypatch.setenv("CONSUL_URL", consul_url)
    monkeypatch.delenv("TRAEFIK_POINT_ENTREE", raising=False)
    nom, instance = squelette.nom, f"{squelette.nom}-test"
    app = _creer_app(squelette, database_url, instance=instance, consul_actif=True)

    async with httpx.AsyncClient(base_url=consul_url, timeout=5.0) as consul:

        async def inscrits_dans_consul() -> str:
            services = (await consul.get("/v1/agent/services")).json()
            return f"services de l'agent : {sorted(services)}"

        async with AsyncExitStack() as pile:
            await _borne(
                f"démarrage du lifespan ({nom}, inscription dans Consul)",
                pile.enter_async_context(app.router.lifespan_context(app)),
                inscrits_dans_consul,
            )
            services = await _consul_json(consul, "/v1/agent/services")
            checks = await _checks_executes(consul, nom)
            await _borne(
                f"arrêt du lifespan ({nom}, retrait de Consul)", pile.aclose(), inscrits_dans_consul
            )

        apres_arret = await _consul_json(consul, "/v1/agent/services")

    inscrits = [s for s in services.values() if s["Service"] == nom]
    assert len(inscrits) == 1, services
    inscrit = inscrits[0]
    check = [c for c in checks.values() if c["ServiceID"] == inscrit["ID"]]
    assert len(check) == 1, checks
    # L'agent ne renvoie pas l'URL du check : elle figure dans sa sortie après la première
    # exécution (ici un échec de résolution, l'instance <nom>-test n'existant pas sur le réseau).
    assert check[0]["Type"] == "http"
    assert f"http://{instance}:8000/health" in check[0]["Output"], check[0]["Output"]
    assert inscrit["Meta"]["metriques"] == "/metrics"

    tags = inscrit["Tags"]
    ressource = squelette.ressource
    # Route du préfixe (E2).
    assert set(tags) >= {
        "traefik.enable=true",
        f"traefik.http.routers.{nom}.rule=PathPrefix(`/api/v1/{ressource}`)",
        f"traefik.http.routers.{nom}.entrypoints=web",
        f"traefik.http.routers.{nom}.middlewares=standard@file",
    }
    # Route de santé (Q2, option a) : Path(/api/v1/<ressource>/health) réécrit en /health,
    # sur la chaîne standard@file.
    reecritures = _middlewares_replace_path(tags, "/health")
    sante = [
        routeur
        for routeur in _routeurs(tags).values()
        if f"Path(`/api/v1/{ressource}/health`)" in _termes_de_regle(routeur.get("rule", ""))
    ]
    assert len(sante) == 1, f"aucun routeur de santé dans les tags : {tags}"
    middlewares = sante[0].get("middlewares", "").split(",")
    assert "standard@file" in middlewares, tags
    # Middleware déclaré dans les tags du service : référencé seul ou suffixé @consulcatalog.
    references = {m.removesuffix("@consulcatalog") for m in middlewares}
    assert reecritures & references, f"aucune réécriture vers /health : {tags}"

    assert inscrit["ID"] not in apres_arret
