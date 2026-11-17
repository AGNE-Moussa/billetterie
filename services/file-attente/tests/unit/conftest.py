"""Fixtures des tests unitaires de file-attente : file en mémoire, sans Redis ni Keycloak.

L'application est assemblée par `creer_app`, le lifespan n'est pas démarré (ni Redis, ni Consul,
ni tâche des vagues). `dependency_overrides` remplace `obtenir_file` par `FileEnMemoire`, double
de `StockageFile` (et de `FileRedis.verifier` pour la santé). Chaque méthode s'exécute sans
`await` intermédiaire, donc de façon atomique, comme les scripts Lua.
"""

import secrets
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from commun.faux_jetons import EmetteurDeTest
from file_attente.api.dependances import obtenir_file
from file_attente.config import Parametres
from file_attente.domaine.file import EtatStocke, FileIndisponible, StatutFile
from file_attente.principal import creer_app

MAINTENANT = datetime(2026, 11, 15, 10, 0, tzinfo=UTC)
URL_REDIS = "redis://127.0.0.1:6379/0"
TAILLE_VAGUE = 2
INTERVALLE_VAGUES = 10.0
DUREE_ADMISSION = 600


class FileEnMemoire:
    """Double de `StockageFile` : attente ordonnée par séance, admissions avec échéance.

    `injoignable` : chaque appel lève `FileIndisponible` (Redis absent ou trop lent).
    """

    def __init__(self) -> None:
        self.attente: dict[UUID, list[str]] = {}
        self.admis: dict[tuple[UUID, str], datetime] = {}
        self.injoignable = False
        self.maintenant = MAINTENANT

    def _entrer_appel(self) -> None:
        if self.injoignable:
            raise FileIndisponible()

    def _admission(self, seance_id: UUID, sub: str) -> datetime | None:
        echeance = self.admis.get((seance_id, sub))
        if echeance is not None and echeance <= self.maintenant:
            del self.admis[(seance_id, sub)]
            return None
        return echeance

    def admettre(self, seance_id: UUID, taille: int, duree: int = DUREE_ADMISSION) -> list[str]:
        """Vague : les `taille` premiers entrés passent admis jusqu'à maintenant + `duree`."""
        file = self.attente.setdefault(seance_id, [])
        admis, self.attente[seance_id] = file[:taille], file[taille:]
        for sub in admis:
            self.admis[(seance_id, sub)] = self.maintenant + timedelta(seconds=duree)
        return admis

    async def entrer(self, seance_id: UUID, sub: str) -> tuple[EtatStocke, bool]:
        self._entrer_appel()
        echeance = self._admission(seance_id, sub)
        if echeance is not None:
            return EtatStocke(StatutFile.ADMIS, admission_expire_le=echeance), False
        file = self.attente.setdefault(seance_id, [])
        entre = sub not in file
        if entre:
            file.append(sub)
        return EtatStocke(StatutFile.EN_ATTENTE, rang=file.index(sub)), entre

    async def lire(self, seance_id: UUID, sub: str) -> EtatStocke | None:
        self._entrer_appel()
        echeance = self._admission(seance_id, sub)
        if echeance is not None:
            return EtatStocke(StatutFile.ADMIS, admission_expire_le=echeance)
        file = self.attente.get(seance_id, [])
        if sub not in file:
            return None
        return EtatStocke(StatutFile.EN_ATTENTE, rang=file.index(sub))

    async def verifier(self) -> None:
        self._entrer_appel()


# Le mode importlib de pytest interdit `from conftest import ...` : tout est servi en fixtures.


@pytest.fixture
def cle_admission() -> str:
    return secrets.token_urlsafe(48)


@pytest.fixture
def seance_sous_file() -> UUID:
    return uuid4()


@pytest.fixture
def file_memoire() -> FileEnMemoire:
    return FileEnMemoire()


@pytest.fixture
def emetteur() -> EmetteurDeTest:
    return EmetteurDeTest()


FabriqueApp = Callable[..., FastAPI]


@pytest.fixture
def fabrique_app(
    emetteur: EmetteurDeTest,
    file_memoire: FileEnMemoire,
    seance_sous_file: UUID,
    cle_admission: str,
) -> FabriqueApp:
    """Application sur la file en mémoire ; les arguments nommés vont à `Parametres`.

    `file_absente=True` : aucune file installée (lifespan non démarré), comme si Redis n'avait
    pas pu être créé.
    """

    def fabriquer(*, file_absente: bool = False, **reglages: Any) -> FastAPI:
        reglages.setdefault("redis_url", URL_REDIS)
        reglages.setdefault("seances_sous_file", frozenset({seance_sous_file}))
        reglages.setdefault("admission_cle_signature", cle_admission)
        reglages.setdefault("taille_vague", TAILLE_VAGUE)
        reglages.setdefault("intervalle_vagues", INTERVALLE_VAGUES)
        reglages.setdefault("duree_admission", DUREE_ADMISSION)
        config = Parametres(instance="file-attente-test", consul_actif=False, **reglages)
        application = creer_app(config, verificateur_jetons=emetteur.verificateur())
        if not file_absente:
            application.dependency_overrides[obtenir_file] = lambda: file_memoire
        return application

    return fabriquer


@pytest.fixture
def app(fabrique_app: FabriqueApp) -> FastAPI:
    return fabrique_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def entetes_client(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(
        sujet="client-a", roles=["customer"], scopes=["events:read", "orders:write"]
    )


@pytest.fixture
def entetes_client_b(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(
        sujet="client-b", roles=["customer"], scopes=["events:read", "orders:write"]
    )


@pytest.fixture
def entetes_revendeur(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(
        sujet="sujet-revendeur-test",
        roles=["partner"],
        scopes=["events:read", "orders:write"],
        client="revendeur-test",
    )


@pytest.fixture
def entetes_admin(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(roles=["admin"], scopes=["events:read", "events:write"])


@pytest.fixture
def environnement_propre(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (
        "SEANCES_SOUS_FILE",
        "ADMISSION_CLE_SIGNATURE",
        "TAILLE_VAGUE",
        "INTERVALLE_VAGUES",
        "DUREE_ADMISSION",
        "DELAI_REDIS",
        "REDIS_URL",
    ):
        monkeypatch.delenv(variable, raising=False)
