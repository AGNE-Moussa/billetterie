"""BIL-001 : billets de bout en bout, image construite depuis services/billets/Dockerfile.

Réseau Testcontainers : Consul, Traefik avec la configuration réelle de infra/traefik/, faux
vérificateur du conftest (accepte tout jeton), PostgreSQL 16 (base `billets`), une migration
lancée une fois, puis `billets-1` et `billets-2` démarrés ensemble (plan, Q11 et Q12 : seul
billets est construit en image, les quatre autres sont couverts sans image).

Cas de concurrence adapté (Q11) : il n'existe pas encore de place ; les requêtes simultanées
portent sur la route de santé, routée par la gateway vers les deux instances.

Chaque attente a une échéance mesurée (time.monotonic) et échoue par une assertion qui nomme
l'étape et le dernier état observé (statut, check Consul, journaux) : pytest-timeout n'est pas
dans le projet.
"""

import json
import secrets
import threading
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Iterator
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
DOCKERFILE = "services/billets/Dockerfile"
IMAGE_POSTGRES = "postgres:16.10-alpine"
INSTANCES = ("billets-1", "billets-2")
ROUTE_SANTE = "/api/v1/seats/health"
# Le faux vérificateur accepte tout jeton : la chaîne standard@file en exige un.
JETON = {"Authorization": "Bearer jeton-de-test"}
APPELS_SIMULTANES = 40
# Échéance d'une étape (démarrage, migration, gateway, Consul) : large pour un poste lent.
DELAI_ETAPE = 120.0
# Construction de l'image (uv sync complet sans cache sur un poste lent) : seule exception.
DELAI_CONSTRUCTION = 600.0
DELAI_APPEL = 10.0
DELAI_OBSERVATION = 10.0
CONNEXION_BORNEE = {"timeout": 30, "command_timeout": 30}

Observation = Callable[[], Awaitable[str]]


@dataclass
class Plateforme:
    instances: dict[str, DockerContainer]
    url_base_hote: str
    code_migration: int | None
    journal_migration: str


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
def base_billets(reseau: Network, borne: Any, journal: Any) -> Iterator[tuple[str, str]]:
    """Base `billets` sur le réseau (alias postgres) : (URL vue des conteneurs, vue de l'hôte)."""
    mot_de_passe = secrets.token_urlsafe(16)
    pg = PostgresContainer(
        IMAGE_POSTGRES, username="billets", password=mot_de_passe, dbname="billets"
    )
    pg.with_network(reseau).with_network_aliases("postgres")
    borne("démarrage de PostgreSQL (billets)", DELAI_ETAPE, pg.start, lambda: journal(pg))
    try:
        hote = pg.get_container_host_ip().replace("localhost", "127.0.0.1")
        yield (
            f"postgresql+asyncpg://billets:{mot_de_passe}@postgres:5432/billets",
            f"postgresql+asyncpg://billets:{mot_de_passe}@{hote}:{pg.get_exposed_port(5432)}/billets",
        )
    finally:
        borne("arrêt de PostgreSQL (billets)", DELAI_ETAPE, pg.stop, lambda: journal(pg))


def _migrer_une_fois(
    image: str, reseau: Network, url_reseau: str, borne: Any, journal: Any
) -> tuple[int | None, str]:
    """Comme billets-migrations dans le compose : même image, une seule fois.

    Renvoie (code de sortie, journal) ; code None si l'échéance est dépassée, le test le
    signale alors par une assertion qui reprend le journal.
    """
    migration = (
        DockerContainer(image)
        .with_command("alembic upgrade head")
        .with_env("DATABASE_URL", url_reseau)
        .with_network(reseau)
    )
    borne(
        "démarrage de la migration (billets)",
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
        texte = journal(migration)
        if code is None:
            texte = (
                f"migration toujours en cours après {time.monotonic() - debut:.0f} s "
                f"(échéance {DELAI_ETAPE:.0f} s) ; journal :\n{texte}"
            )
        return code, texte
    finally:
        borne(
            "arrêt de la migration (billets)",
            DELAI_ETAPE,
            migration.stop,
            lambda: journal(migration),
        )


def _demarrer_ensemble(instances: dict[str, DockerContainer], journal: Any) -> None:
    """Démarre les instances en même temps (un fil démon chacune), échéance commune mesurée."""
    erreurs: dict[str, BaseException] = {}

    def demarrer(nom: str, conteneur: DockerContainer) -> None:
        try:
            conteneur.start()
        except BaseException as erreur:  # noqa: BLE001 : relevée par le fil appelant
            erreurs[nom] = erreur

    fils = [
        threading.Thread(target=demarrer, args=(nom, c), name=f"demarrage {nom}", daemon=True)
        for nom, c in instances.items()
    ]
    debut = time.monotonic()
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=max(0.0, debut + DELAI_ETAPE - time.monotonic()))
    en_cours = [fil.name for fil in fils if fil.is_alive()]
    if en_cours:
        journaux = {nom: journal(c) for nom, c in instances.items()}
        raise AssertionError(
            f"démarrage simultané des instances : échéance de {DELAI_ETAPE:.0f} s dépassée "
            f"({time.monotonic() - debut:.0f} s mesurées) pour {en_cours} ; journaux : {journaux}"
        )
    if erreurs:
        raise next(iter(erreurs.values()))


@pytest.fixture(scope="module")
def plateforme(
    reseau: Network,
    consul_url: str,
    gateway_url: str,
    base_billets: tuple[str, str],
    borne: Any,
    journal: Any,
) -> Iterator[Plateforme | None]:
    """Migration unique puis les deux instances démarrées en même temps.

    None si le Dockerfile n'existe pas encore : chaque test le signale par une assertion.
    """
    if not (RACINE / DOCKERFILE).is_file():
        yield None
        return
    url_reseau, url_hote = base_billets
    image = DockerImage(
        path=str(RACINE), dockerfile_path=DOCKERFILE, tag="billetterie/billets:test"
    )
    borne(
        "construction de l'image billetterie/billets:test",
        DELAI_CONSTRUCTION,
        image.build,
        lambda: "construction docker toujours en cours",
    )
    instances: dict[str, DockerContainer] = {}
    try:
        code, journal_migration = _migrer_une_fois(str(image), reseau, url_reseau, borne, journal)
        instances = {
            nom: DockerContainer(str(image))
            .with_env("DATABASE_URL", url_reseau)
            .with_env("CONSUL_URL", "http://consul:8500")
            .with_env("INSTANCE", nom)
            .with_network(reseau)
            .with_network_aliases(nom)
            for nom in INSTANCES
        }
        if code == 0:
            _demarrer_ensemble(instances, journal)
        yield Plateforme(instances, url_hote, code, journal_migration)
    finally:
        for nom, conteneur in instances.items():
            if conteneur._container is not None:  # noqa: SLF001 : démarré
                borne(
                    f"arrêt de {nom}", DELAI_ETAPE, conteneur.stop, lambda c=conteneur: journal(c)
                )
        borne(
            "suppression de l'image billets",
            DELAI_ETAPE,
            image.remove,
            lambda: "suppression en cours",
        )


def _image_construite(plateforme: Plateforme | None) -> Plateforme:
    assert plateforme is not None, f"{DOCKERFILE} absent : image de billets non construite"
    assert plateforme.code_migration == 0, (
        f"la migration unique a échoué (code {plateforme.code_migration}) :\n"
        f"{plateforme.journal_migration}"
    )
    return plateforme


def _journaux(plateforme: Plateforme, journal: Any) -> str:
    return "\n".join(f"--- {nom} ---\n{journal(c)}" for nom, c in plateforme.instances.items())


async def _attendre_route(
    client: httpx.AsyncClient, plateforme: Plateforme, journal: Any, delai: float = DELAI_ETAPE
) -> None:
    """Attend que Traefik ait découvert la route de santé (404 tant qu'elle n'existe pas)."""
    debut = time.monotonic()
    dernier = "aucune réponse"
    while time.monotonic() < debut + delai:
        try:
            reponse = await client.get(ROUTE_SANTE, headers=JETON, timeout=DELAI_APPEL)
        except httpx.HTTPError as erreur:
            dernier = f"erreur {erreur!r}"
        else:
            if reponse.status_code != 404:
                return
            dernier = f"{reponse.status_code} {reponse.text[:200]!r}"
        await anyio.sleep(1)
    raise AssertionError(
        f"découverte de {ROUTE_SANTE} par Traefik : échéance de {delai:.0f} s dépassée "
        f"({time.monotonic() - debut:.0f} s mesurées) ; dernière réponse : {dernier} ; "
        f"journaux des instances :\n{_journaux(plateforme, journal)}"
    )


def _appels_traites(conteneur: DockerContainer, prefixe: str) -> int:
    """Lignes du journal d'accès d'uvicorn (JSON) dont la corrélation commence par `prefixe`."""
    sortie, erreurs = conteneur.get_logs()
    total = 0
    for ligne in (sortie + erreurs).decode("utf-8", errors="replace").splitlines():
        try:
            entree = json.loads(ligne)
        except json.JSONDecodeError:
            continue
        if entree.get("journal") == "uvicorn.access" and str(
            entree.get("correlation_id") or ""
        ).startswith(prefixe):
            total += 1
    return total


async def test_la_sante_de_billets_repond_via_la_gateway(
    gateway_url: str, plateforme: Plateforme | None, journal: Any
) -> None:
    prete = _image_construite(plateforme)
    async with httpx.AsyncClient(base_url=gateway_url, timeout=DELAI_APPEL) as client:
        await _attendre_route(client, prete, journal)

        reponse = await _borne(
            f"GET {ROUTE_SANTE} via la gateway", client.get(ROUTE_SANTE, headers=JETON)
        )

    assert reponse.status_code == 200, reponse.text
    assert reponse.headers["content-type"] == "application/json"
    assert reponse.json() == {"statut": "ok"}
    assert reponse.headers.get("X-Correlation-Id")


async def test_des_requetes_simultanees_sur_billets_se_repartissent_sur_ses_deux_instances(
    gateway_url: str, plateforme: Plateforme | None, journal: Any
) -> None:
    prete = _image_construite(plateforme)
    prefixe = f"concurrence-{secrets.token_hex(4)}-"
    sans_plafond = httpx.Limits(max_connections=None, max_keepalive_connections=None)
    reponses: list[httpx.Response] = []
    async with httpx.AsyncClient(
        base_url=gateway_url, limits=sans_plafond, timeout=DELAI_APPEL
    ) as client:
        await _attendre_route(client, prete, journal)
        # Laisse le seau de limite-generale se remplir après les appels d'attente.
        await anyio.sleep(3)

        async def appel(numero: int) -> None:
            entetes = {**JETON, "X-Correlation-Id": f"{prefixe}{numero}"}
            reponses.append(await client.get(ROUTE_SANTE, headers=entetes))

        async def simultanes() -> None:
            async with anyio.create_task_group() as groupe:
                for numero in range(APPELS_SIMULTANES):
                    groupe.start_soon(appel, numero)

        async def recues() -> str:
            return f"{len(reponses)} réponses reçues sur {APPELS_SIMULTANES} : " + str(
                Counter(r.status_code for r in reponses)
            )

        await _borne(f"{APPELS_SIMULTANES} appels simultanés via la gateway", simultanes(), recues)

    codes = Counter(reponse.status_code for reponse in reponses)
    assert codes == {200: APPELS_SIMULTANES}, codes
    assert all(reponse.json() == {"statut": "ok"} for reponse in reponses)

    par_instance = {
        nom: _appels_traites(conteneur, prefixe) for nom, conteneur in prete.instances.items()
    }
    assert all(nombre >= 1 for nombre in par_instance.values()), par_instance
    assert sum(par_instance.values()) == APPELS_SIMULTANES, par_instance


def _sante_docker(conteneur: DockerContainer) -> dict[str, Any]:
    """État de santé Docker : statut et sortie du dernier HEALTHCHECK."""
    enveloppe = conteneur.get_wrapped_container()
    enveloppe.reload()
    sante = enveloppe.attrs.get("State", {}).get("Health") or {}
    derniers = sante.get("Log") or [{}]
    return {"Status": sante.get("Status"), "Output": str(derniers[-1].get("Output", ""))[-300:]}


async def _checks_billets(consul: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Instances de billets dans Consul et leurs checks (nœud et service)."""
    entrees = (await consul.get("/v1/health/service/billets")).json()
    return [
        {
            "Address": entree["Service"]["Address"],
            "Checks": [
                {"Status": check["Status"], "Output": check["Output"][-300:]}
                for check in entree["Checks"]
            ],
        }
        for entree in entrees
    ]


async def test_les_deux_instances_de_billets_demarrent_ensemble_apres_une_seule_migration(
    consul_url: str, plateforme: Plateforme | None, journal: Any
) -> None:
    prete = _image_construite(plateforme)

    debut = time.monotonic()
    etats: dict[str, str | None] = {}
    sante: dict[str, dict[str, Any]] = {}
    checks: list[dict[str, Any]] = []
    passing: set[str] = set()
    derniere_erreur: str | None = None
    async with httpx.AsyncClient(base_url=consul_url, timeout=DELAI_APPEL) as consul:
        while time.monotonic() < debut + DELAI_ETAPE:
            sante = {
                nom: await _borne(
                    f"lecture de l'état Docker de {nom}",
                    anyio.to_thread.run_sync(_sante_docker, c, abandon_on_cancel=True),
                )
                for nom, c in prete.instances.items()
            }
            etats = {nom: etat["Status"] for nom, etat in sante.items()}
            try:
                checks = await _checks_billets(consul)
                derniere_erreur = None
            except (httpx.HTTPError, ValueError, KeyError) as erreur:
                derniere_erreur = repr(erreur)
            # Comme ?passing=1 : une instance compte si tous ses checks sont au vert.
            passing = {
                e["Address"] for e in checks if all(c["Status"] == "passing" for c in e["Checks"])
            }
            if set(etats.values()) == {"healthy"} and passing == set(INSTANCES):
                break
            await anyio.sleep(2)

    diagnostic = (
        f"après {time.monotonic() - debut:.0f} s (échéance {DELAI_ETAPE:.0f} s) ; "
        f"HEALTHCHECK Docker : {sante} ; checks Consul : {checks}"
        + (f" ; dernière erreur Consul : {derniere_erreur}" if derniere_erreur else "")
    )
    assert etats == dict.fromkeys(INSTANCES, "healthy"), (
        f"{etats} {diagnostic}\n{_journaux(prete, journal)}"
    )
    assert passing == set(INSTANCES), f"{passing} {diagnostic}"

    async def lire_versions() -> list[str]:
        moteur = create_async_engine(prete.url_base_hote, connect_args=CONNEXION_BORNEE)
        try:
            async with moteur.connect() as connexion:
                lignes = await connexion.execute(sa.text("SELECT version_num FROM alembic_version"))
                return [ligne[0] for ligne in lignes]
        finally:
            await moteur.dispose()

    versions = await _borne("lecture de alembic_version (billets)", lire_versions())
    assert versions == ["0001"]
