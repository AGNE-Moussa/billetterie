"""Squelettes des services métier (BIL-001) : tests paramétrés sur la table `SERVICES`.

Sans Docker : application assemblée par `creer_app`, base SQLite en mémoire ou port fermé,
Consul désactivé (ou remplacé par un faux Consul HTTP local), lecture des fichiers du dépôt.
Aucune copie par service : un nouveau service s'ajoute à la table.
"""

import importlib
import io
import json
import re
import secrets
import subprocess
import sys
import threading
import tomllib
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
import yaml
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI

from commun.faux_jetons import EmetteurDeTest
from commun.registre import VARIABLE_POINT_ENTREE, tags_sante_traefik, tags_traefik

pytestmark = pytest.mark.anyio

RACINE = Path(__file__).resolve().parents[2]
CI = RACINE / ".github" / "workflows" / "ci.yml"
ROUTES_DOCUMENTATION = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
CORRELATION = "correlation-test-01"


@dataclass(frozen=True)
class Service:
    nom: str
    ressource: str
    base: str
    instances: tuple[str, ...]

    @property
    def dossier(self) -> Path:
        return RACINE / "services" / self.nom

    @property
    def paquet(self) -> str:
        return f"billetterie-{self.nom}"


# Données communes du plan (docs/test-plans/BIL-001.md), déclarées une seule fois.
SERVICES = [
    Service("catalogue", "events", "catalogue", ("catalogue-1",)),
    Service("billets", "seats", "billets", ("billets-1", "billets-2")),
    Service("commandes", "orders", "commandes", ("commandes-1", "commandes-2")),
    Service("paiements", "payments", "paiements", ("paiements-1",)),
    Service("notifications", "notifications", "notifications", ("notifications-1",)),
]
PAR_SERVICE = pytest.mark.parametrize("service", SERVICES, ids=[s.nom for s in SERVICES])


def _module(service: Service, chemin: str) -> ModuleType:
    return importlib.import_module(f"{service.nom}.{chemin}")


def _url_synthetique(service: Service, port: int = 5432) -> str:
    mot_de_passe = secrets.token_urlsafe(16)
    return f"postgresql+asyncpg://{service.nom}:{mot_de_passe}@127.0.0.1:{port}/{service.base}"


def _creer_app(
    service: Service,
    database_url: str,
    emetteur: EmetteurDeTest | None = None,
    **options: Any,
) -> FastAPI:
    """Application du service ; jetons vérifiés avec la clé de `emetteur` (pas de Keycloak)."""
    config = _module(service, "config").Parametres(
        database_url=database_url, instance=f"{service.nom}-test", **options
    )
    app: FastAPI = _module(service, "principal").creer_app(
        config, verificateur_jetons=(emetteur or EmetteurDeTest()).verificateur()
    )
    return app


@asynccontextmanager
async def _client(app: FastAPI, demarrer: bool = True) -> AsyncIterator[httpx.AsyncClient]:
    """Client ASGI ; `demarrer` lance le lifespan (base ouverte, Consul selon la config)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        if demarrer:
            async with app.router.lifespan_context(app):
                yield client
        else:
            yield client


def _charger_yaml(fichier: Path) -> dict[str, Any]:
    contenu: dict[str, Any] = yaml.safe_load(fichier.read_text(encoding="utf-8")) or {}
    return contenu


def _racine_pyproject() -> dict[str, Any]:
    return tomllib.loads((RACINE / "pyproject.toml").read_text(encoding="utf-8"))


def _membres() -> list[str]:
    membres: list[str] = _racine_pyproject()["tool"]["uv"]["workspace"]["members"]
    return membres


def _lignes_dockerfile(fichier: Path) -> list[str]:
    """Lignes logiques : les continuations `\\` sont jointes."""
    texte = fichier.read_text(encoding="utf-8").replace("\\\n", " ")
    return [ligne.strip() for ligne in texte.splitlines() if ligne.strip()]


# --- E1 : contrat, santé, corrélation, métriques, workspace, arborescence -----------------------


@PAR_SERVICE
def test_chaque_contrat_ne_declare_que_get_health(service: Service) -> None:
    contrat = _charger_yaml(service.dossier / "openapi.yaml")

    assert set(contrat["paths"]) == {"/health"}
    assert set(contrat["paths"]["/health"]) == {"get"}
    operation = contrat["paths"]["/health"]["get"]
    assert operation["operationId"] == "sante"
    reponses = operation["responses"]
    assert set(reponses) == {"200", "503"}
    assert reponses["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Sante"
    }
    assert reponses["503"]["content"]["application/problem+json"]["schema"] == {
        "$ref": "#/components/schemas/Probleme"
    }
    assert contrat["info"]["title"] == f"Service {service.nom}"
    assert contrat["info"]["version"] == "0.1.0"
    assert "servers" not in contrat
    assert "securitySchemes" not in contrat.get("components", {})
    assert set(contrat["components"]["schemas"]) == {"Probleme", "Sante"}


@PAR_SERVICE
async def test_la_sante_de_chaque_service_repond_ok(service: Service) -> None:
    app = _creer_app(service, "sqlite+aiosqlite://", consul_actif=False)

    async with _client(app) as client:
        reponse = await client.get("/health")

    assert reponse.status_code == 200
    assert reponse.headers["content-type"] == "application/json"
    assert reponse.json() == {"statut": "ok"}


@PAR_SERVICE
async def test_la_sante_de_chaque_service_repond_503_quand_sa_base_ne_repond_pas(
    service: Service,
) -> None:
    # Port 1 fermé : la connexion est refusée tout de suite.
    url = f"postgresql+asyncpg://test:{secrets.token_urlsafe(16)}@127.0.0.1:1/{service.base}"
    app = _creer_app(service, url, consul_actif=False)

    async with _client(app) as client:
        reponse = await client.get("/health")

    assert reponse.status_code == 503
    assert reponse.headers["content-type"] == "application/problem+json"
    probleme = reponse.json()
    assert probleme["code"] == "BASE_INDISPONIBLE"
    assert probleme["status"] == 503


@PAR_SERVICE
async def test_chaque_service_repond_avec_un_identifiant_de_correlation(
    service: Service,
) -> None:
    app = _creer_app(service, "sqlite+aiosqlite://", consul_actif=False)

    async with _client(app) as client:
        reponse = await client.get("/health", headers={"X-Correlation-Id": CORRELATION})

    assert reponse.headers["X-Correlation-Id"] == CORRELATION


@PAR_SERVICE
async def test_chaque_service_expose_ses_metriques(service: Service) -> None:
    app = _creer_app(service, _url_synthetique(service), consul_actif=False)

    async with _client(app, demarrer=False) as client:
        reponse = await client.get("/metrics")

    assert reponse.status_code == 200
    assert reponse.headers["content-type"].startswith("text/plain")
    assert "/metrics" not in app.openapi()["paths"]


@PAR_SERVICE
def test_chaque_service_est_declare_dans_le_workspace_mypy_et_ruff(service: Service) -> None:
    racine = _racine_pyproject()
    projet = tomllib.loads((service.dossier / "pyproject.toml").read_text(encoding="utf-8"))

    assert f"services/{service.nom}" in racine["tool"]["uv"]["workspace"]["members"]
    assert service.paquet in racine["tool"]["uv"]["sources"]
    assert f"services/{service.nom}/src" in racine["tool"]["mypy"]["files"]
    assert service.nom in racine["tool"]["ruff"]["lint"]["isort"]["known-first-party"]
    assert projet["project"]["name"] == service.paquet
    assert projet["project"]["version"] == "0.1.0"
    assert projet["tool"]["uv"]["build-backend"]["module-name"] == service.nom


@PAR_SERVICE
def test_chaque_service_suit_l_arborescence_d_echo(service: Service) -> None:
    attendus = [
        "openapi.yaml",
        "Dockerfile",
        "alembic.ini",
        "alembic/env.py",
        "alembic/versions",
        f"src/{service.nom}/config.py",
        f"src/{service.nom}/principal.py",
        f"src/{service.nom}/api",
        f"src/{service.nom}/domaine",
        f"src/{service.nom}/infra",
        "README.md",
    ]

    absents = [chemin for chemin in attendus if not (service.dossier / chemin).exists()]

    assert absents == []


# --- E2 : tags Consul et préfixes ---------------------------------------------------------------


@PAR_SERVICE
def test_chaque_service_annonce_la_route_de_son_prefixe(
    service: Service, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(VARIABLE_POINT_ENTREE, raising=False)
    principal = _module(service, "principal")

    tags = tags_traefik(principal.NOM_SERVICE, *principal.RESSOURCES)

    assert service.nom == principal.NOM_SERVICE
    assert tags == [
        "traefik.enable=true",
        f"traefik.http.routers.{service.nom}.rule=PathPrefix(`/api/v1/{service.ressource}`)",
        f"traefik.http.routers.{service.nom}.entrypoints=web",
        f"traefik.http.routers.{service.nom}.middlewares=standard@file",
    ]


def test_les_prefixes_des_services_sont_distincts() -> None:
    ressources = [r for s in SERVICES for r in _module(s, "principal").RESSOURCES]
    ressources_echo = list(importlib.import_module("echo.principal").RESSOURCES)
    ressources += ressources_echo
    # Une ressource par service de la table, plus celle(s) d'echo.
    attendu = len(SERVICES) + len(ressources_echo)

    assert len(ressources) == attendu
    assert len(set(ressources)) == attendu
    assert importlib.import_module("catalogue.principal").RESSOURCES == ("events",)
    prefixes = [f"/api/v1/{r}" for r in ressources]
    for prefixe in prefixes:
        for autre in prefixes:
            if autre != prefixe:
                assert not autre.startswith(prefixe), (prefixe, autre)


class _FauxConsul(BaseHTTPRequestHandler):
    """Agent Consul minimal : garde le corps de chaque inscription, répond 200."""

    inscriptions: list[dict[str, Any]]

    def do_PUT(self) -> None:  # noqa: N802 (nom imposé par http.server)
        longueur = int(self.headers.get("Content-Length") or 0)
        corps = self.rfile.read(longueur)
        if self.path == "/v1/agent/service/register":
            self.server.inscriptions.append(json.loads(corps))  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_args: Any) -> None:
        pass


@pytest.fixture
def faux_consul(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), _FauxConsul)
    serveur.inscriptions = []  # type: ignore[attr-defined]
    fil = threading.Thread(target=serveur.serve_forever, daemon=True)
    fil.start()
    monkeypatch.setenv("CONSUL_URL", f"http://127.0.0.1:{serveur.server_address[1]}")
    monkeypatch.delenv(VARIABLE_POINT_ENTREE, raising=False)
    try:
        yield serveur.inscriptions  # type: ignore[attr-defined]
    finally:
        serveur.shutdown()
        serveur.server_close()


def _routeurs(tags: list[str]) -> dict[str, dict[str, str]]:
    routeurs: dict[str, dict[str, str]] = {}
    for tag in tags:
        cle, _, valeur = tag.partition("=")
        trouve = re.fullmatch(r"traefik\.http\.routers\.([^.]+)\.(.+)", cle)
        if trouve:
            routeurs.setdefault(trouve.group(1), {})[trouve.group(2).lower()] = valeur
    return routeurs


def _reecritures_vers_health(tags: list[str]) -> set[str]:
    """Middlewares déclarés dans les tags qui remplacent le chemin par `/health`."""
    noms: set[str] = set()
    for tag in tags:
        cle, _, valeur = tag.partition("=")
        trouve = re.fullmatch(r"traefik\.http\.middlewares\.([^.]+)\.replacepath\.path", cle, re.I)
        if trouve and valeur == "/health":
            noms.add(trouve.group(1))
    return noms


def _termes_de_regle(regle: str) -> list[str]:
    """Conditions d'une règle Traefik combinées en ET ; une règle avec `||` reste entière."""
    if "||" in regle:
        return [regle.strip()]
    return [terme.strip() for terme in regle.split("&&")]


@PAR_SERVICE
async def test_les_tags_de_sante_routent_le_prefixe_vers_health(
    service: Service, faux_consul: list[dict[str, Any]]
) -> None:
    """Tags réellement envoyés à Consul au démarrage de l'instance (option (a) de Q2)."""
    app = _creer_app(service, "sqlite+aiosqlite://", consul_actif=True)

    async with app.router.lifespan_context(app):
        pass

    assert len(faux_consul) == 1
    tags: list[str] = faux_consul[0]["Tags"]
    routeurs = _routeurs(tags)
    chemin = f"/api/v1/{service.ressource}/health"
    sante = [nom for nom, props in routeurs.items() if chemin in props.get("rule", "")]
    assert len(sante) == 1, f"aucun routeur (ou plusieurs) sur {chemin} : {tags}"
    routeur = routeurs[sante[0]]
    # Règle `Path(...)`, éventuellement combinée en ET (`&&`) à d'autres conditions.
    assert f"Path(`{chemin}`)" in _termes_de_regle(routeur["rule"])
    assert routeur["entrypoints"] == "web"
    middlewares = [m.strip() for m in routeur.get("middlewares", "").split(",") if m.strip()]
    assert "standard@file" in middlewares
    locaux = {m.removesuffix("@consulcatalog") for m in middlewares}
    assert locaux & _reecritures_vers_health(tags), "aucun middleware ne réécrit en /health"
    # Le routeur du préfixe reste en place.
    assert routeurs[service.nom]["rule"] == f"PathPrefix(`/api/v1/{service.ressource}`)"


@PAR_SERVICE
async def test_le_routeur_de_sante_passe_avant_celui_du_prefixe(
    service: Service, faux_consul: list[dict[str, Any]]
) -> None:
    """Priorité explicite du routeur de santé, strictement supérieure à celle du routeur du
    préfixe (explicite, ou implicite : longueur de la règle chez Traefik)."""
    app = _creer_app(service, "sqlite+aiosqlite://", consul_actif=True)

    async with app.router.lifespan_context(app):
        pass

    assert len(faux_consul) == 1
    tags: list[str] = faux_consul[0]["Tags"]
    routeurs = _routeurs(tags)
    chemin = f"/api/v1/{service.ressource}/health"
    sante = [props for props in routeurs.values() if chemin in props.get("rule", "")]
    assert len(sante) == 1, f"aucun routeur (ou plusieurs) sur {chemin} : {tags}"
    assert "priority" in sante[0], f"routeur de santé sans priorité explicite : {tags}"
    assert re.fullmatch(r"\d+", sante[0]["priority"]), sante[0]["priority"]
    prefixe = routeurs[service.nom]
    priorite_prefixe = int(prefixe.get("priority") or len(prefixe["rule"]))
    assert int(sante[0]["priority"]) > priorite_prefixe


@PAR_SERVICE
async def test_le_routeur_de_sante_n_accepte_que_get(
    service: Service, faux_consul: list[dict[str, Any]]
) -> None:
    app = _creer_app(service, "sqlite+aiosqlite://", consul_actif=True)

    async with app.router.lifespan_context(app):
        pass

    assert len(faux_consul) == 1
    tags: list[str] = faux_consul[0]["Tags"]
    chemin = f"/api/v1/{service.ressource}/health"
    sante = [p for p in _routeurs(tags).values() if chemin in p.get("rule", "")]
    assert len(sante) == 1, f"aucun routeur (ou plusieurs) sur {chemin} : {tags}"
    assert set(_termes_de_regle(sante[0]["rule"])) == {
        f"Path(`{chemin}`)",
        "Method(`GET`)",
    }, sante[0]["rule"]


def test_le_routeur_de_sante_refuse_une_ressource_vide() -> None:
    with pytest.raises(ValueError):
        tags_sante_traefik("x", "")


# --- E3 : migration initiale vide, base du service -----------------------------------------------


@PAR_SERVICE
def test_chaque_service_a_une_seule_migration_initiale_vide(service: Service) -> None:
    ini = service.dossier / "alembic.ini"
    assert ini.is_file(), f"{ini} absent"
    assert (service.dossier / "alembic" / "versions" / "0001_initiale.py").is_file()

    scripts = ScriptDirectory.from_config(Config(str(ini)))
    revisions = list(scripts.walk_revisions())

    assert [r.revision for r in revisions] == ["0001"]
    assert revisions[0].down_revision is None
    assert scripts.get_heads() == ["0001"]
    assert dict(_module(service, "infra.base").Base.metadata.tables) == {}


@PAR_SERVICE
def test_l_environnement_alembic_ne_charge_pas_les_tables_de_messagerie(
    service: Service, monkeypatch: pytest.MonkeyPatch
) -> None:
    ini = service.dossier / "alembic.ini"
    assert ini.is_file(), f"{ini} absent"
    assert (service.dossier / "alembic" / "env.py").is_file()
    monkeypatch.setenv("DATABASE_URL", _url_synthetique(service))
    sortie = io.StringIO()

    command.upgrade(Config(str(ini), output_buffer=sortie), "head", sql=True)

    sql = sortie.getvalue()
    tables = re.findall(r"CREATE TABLE\s+(\w+)", sql, re.IGNORECASE)
    assert tables == ["alembic_version"]
    assert "outbox" not in sql
    assert "messages_traites" not in sql


@PAR_SERVICE
def test_chaque_service_a_sa_base_dans_l_init_postgres(service: Service) -> None:
    variable = f"{service.base.upper()}_DB_PASSWORD"
    script = (RACINE / "infra" / "postgres" / "init" / "01-bases.sh").read_text(encoding="utf-8")
    boucle = re.search(r"^for service in (.+); do$", script, re.MULTILINE)
    postgres = _charger_yaml(RACINE / "compose.yaml")["services"]["postgres"]
    exemple = (RACINE / ".env.example").read_text(encoding="utf-8").splitlines()

    assert boucle is not None
    assert service.base in boucle.group(1).split()
    assert re.fullmatch(rf"\$\{{{variable}:\?.+\}}", str(postgres["environment"][variable])), (
        postgres["environment"].get(variable)
    )
    assert f"{variable}=" in exemple


# --- C1 : aucune logique métier ------------------------------------------------------------------


def _chemins(routes: Sequence[Any], prefixe: str = "") -> list[str]:
    """Chemins de toutes les routes, routeurs inclus dépliés (FastAPI les garde imbriqués)."""
    chemins: list[str] = []
    for route in routes:
        chemin = prefixe + str(getattr(route, "path", "") or "")
        imbriquees = getattr(route, "routes", None)
        if imbriquees is None and hasattr(route, "original_router"):
            imbriquees = route.original_router.routes
        if imbriquees is not None:
            chemins += _chemins(imbriquees, chemin)
        else:
            chemins.append(chemin)
    return chemins


@PAR_SERVICE
def test_chaque_service_n_expose_que_la_sante_et_les_metriques(service: Service) -> None:
    app = _creer_app(service, _url_synthetique(service), consul_actif=False)

    chemins = set(_chemins(app.routes)) - ROUTES_DOCUMENTATION

    assert chemins == {"/health", "/metrics"}
    assert set(app.openapi()["paths"]) == {"/health"}


@PAR_SERVICE
async def test_une_route_sous_le_prefixe_du_service_n_existe_pas_encore(
    service: Service,
) -> None:
    emetteur = EmetteurDeTest()
    app = _creer_app(service, _url_synthetique(service), emetteur=emetteur, consul_actif=False)
    entetes = emetteur.entetes(client="services", scopes=["openid"])
    prefixe = f"/api/v1/{service.ressource}"

    async with _client(app, demarrer=False) as client:
        lecture = await client.get(prefixe, headers=entetes)
        ecriture = await client.post(prefixe, headers=entetes, json={})

    assert lecture.status_code == 404
    assert lecture.headers["content-type"] == "application/problem+json"
    assert ecriture.status_code in (404, 405)
    assert ecriture.headers["content-type"] == "application/problem+json"
    for reponse in (lecture, ecriture):
        assert set(reponse.json()) <= {
            "type",
            "title",
            "status",
            "detail",
            "code",
            "correlation_id",
            "erreurs",
        }


@PAR_SERVICE
def test_aucun_service_ne_declare_de_table_ni_d_evenement(service: Service) -> None:
    sources = service.dossier / "src" / service.nom
    usages = [
        fichier.relative_to(RACINE).as_posix()
        for fichier in sources.rglob("*.py")
        if re.search(r"commun\.(outbox|consommateurs)", fichier.read_text(encoding="utf-8"))
    ]

    assert dict(_module(service, "infra.base").Base.metadata.tables) == {}
    assert usages == []


# --- CA1 : image de chaque service --------------------------------------------------------------


@PAR_SERVICE
def test_chaque_dockerfile_declare_un_healthcheck_sur_health(service: Service) -> None:
    dockerfile = service.dossier / "Dockerfile"
    assert dockerfile.is_file(), f"{dockerfile} absent"
    lignes = _lignes_dockerfile(dockerfile)

    sondes = [ligne for ligne in lignes if ligne.startswith("HEALTHCHECK")]
    utilisateurs = [ligne.split()[1] for ligne in lignes if ligne.startswith("USER ")]

    assert len(sondes) == 1
    assert "http://127.0.0.1:8000/health" in sondes[0]
    assert "EXPOSE 8000" in lignes
    assert utilisateurs, "aucune instruction USER"
    assert utilisateurs[-1] not in ("root", "0")


# --- CA3 : la CI couvre les cinq services --------------------------------------------------------


@PAR_SERVICE
def test_la_matrice_images_construit_les_cinq_services(service: Service) -> None:
    job = _charger_yaml(CI)["jobs"]["images"]
    entrees = job["strategy"]["matrix"]["include"]
    construction = next(
        etape["with"]
        for etape in job["steps"]
        if str(etape.get("uses", "")).startswith("docker/build-push-action")
    )

    assert {
        "image": service.nom,
        "context": ".",
        "dockerfile": f"services/{service.nom}/Dockerfile",
    } in entrees
    assert construction["platforms"] == "linux/amd64,linux/arm64"
    assert construction["push"] is False


DOCKERFILES_DU_WORKSPACE = [
    "services/echo/Dockerfile",
    "infra/verificateur/Dockerfile",
    *[f"services/{s.nom}/Dockerfile" for s in SERVICES],
]


@pytest.mark.parametrize("chemin", DOCKERFILES_DU_WORKSPACE)
def test_chaque_dockerfile_copie_le_pyproject_de_chaque_membre_du_workspace(
    chemin: str,
) -> None:
    dockerfile = RACINE / chemin
    assert dockerfile.is_file(), f"{chemin} absent"
    lignes = _lignes_dockerfile(dockerfile)
    premier_sync = next(
        i for i, ligne in enumerate(lignes) if re.match(r"RUN uv sync\b.*--locked", ligne)
    )

    manquants = [
        membre
        for membre in _membres()
        if not any(
            re.fullmatch(rf"COPY {re.escape(membre)}/pyproject\.toml {re.escape(membre)}/", ligne)
            for ligne in lignes[:premier_sync]
        )
    ]

    assert manquants == []


@PAR_SERVICE
def test_chaque_dockerfile_installe_son_paquet_et_lance_son_application(
    service: Service,
) -> None:
    dockerfile = service.dossier / "Dockerfile"
    assert dockerfile.is_file(), f"{dockerfile} absent"
    lignes = _lignes_dockerfile(dockerfile)
    instructions = [ligne for ligne in lignes if not ligne.startswith("#")]
    syncs = [ligne for ligne in instructions if ligne.startswith("RUN uv sync")]
    copies = [ligne.split()[1] for ligne in instructions if ligne.startswith("COPY ")]
    commande = next(ligne for ligne in instructions if ligne.startswith("CMD "))

    assert syncs
    assert all(f"--package {service.paquet}" in ligne for ligne in syncs)
    assert f"services/{service.nom}/alembic.ini" in copies
    assert f"services/{service.nom}/alembic" in copies
    assert f"{service.nom}.principal:creer_app" in commande
    # Ni installation ni lancement d'echo ; la copie de son pyproject.toml reste exigée (workspace).
    texte = "\n".join(instructions)
    assert "echo.principal" not in texte
    assert "billetterie-echo" not in texte


@cache
def _identifiants_collectes(niveau: str) -> tuple[str, ...]:
    """Identifiants des tests collectés par la commande de ce niveau (Makefile, CI)."""
    if niveau == "contract":
        arguments = ["-m", "contract"]
    else:
        dossiers = [f"tests/{niveau}"]
        dossiers += [
            p.relative_to(RACINE).as_posix() for p in RACINE.glob(f"services/*/tests/{niveau}")
        ]
        if niveau == "unit":
            dossiers += [
                p.relative_to(RACINE).as_posix() for p in RACINE.glob("infra/*/tests/unit")
            ]
        arguments = [d for d in dossiers if (RACINE / d).is_dir()]
    resultat = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            *arguments,
        ],
        cwd=RACINE,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    return tuple(ligne for ligne in resultat.stdout.splitlines() if "::" in ligne)


@PAR_SERVICE
@pytest.mark.parametrize("niveau", ["unit", "integration", "contract"])
def test_les_tests_de_chaque_service_sont_collectes(service: Service, niveau: str) -> None:
    identifiants = _identifiants_collectes(niveau)

    assert any(service.nom in identifiant for identifiant in identifiants), (
        f"aucun test {niveau} collecté pour {service.nom}"
    )


@PAR_SERVICE
def test_chaque_paquet_figure_dans_le_lockfile(service: Service) -> None:
    verrou = tomllib.loads((RACINE / "uv.lock").read_text(encoding="utf-8"))

    paquets = [p for p in verrou["package"] if p["name"] == service.paquet]

    assert len(paquets) == 1
    source = paquets[0]["source"]
    assert source.get("editable", source.get("virtual")) == f"services/{service.nom}"
