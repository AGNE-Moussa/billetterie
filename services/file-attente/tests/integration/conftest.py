"""Fixtures d'intégration de file-attente (BIL-015) : vrai Redis 7 (Testcontainers).

- `redis_url` : un Redis jetable par module ; `observateur` le vide avant chaque cas.
- `demarrer_file(**reglages)` : application file-attente sous lifespan (vraie `FileRedis`),
  jetons `EmetteurDeTest`, Consul désactivé. La tâche de fond des vagues tourne avec un
  intervalle d'une heure par défaut : elle ne se déclenche jamais pendant un cas ; les vagues
  sont lancées par le test (`TacheVagues.cycle()`).
- Clé de signature des jetons d'admission générée (`secrets.token_urlsafe`).
"""

import secrets
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from redis.asyncio import Redis
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from commun.faux_jetons import EmetteurDeTest
from file_attente.config import Parametres
from file_attente.infra.file_redis import FileRedis
from file_attente.principal import creer_app
from file_attente.tache import TacheVagues

IMAGE_REDIS = "redis:7.4.6-alpine"
ROUTE_FILES = "/api/v1/queues"
DELAI_APPEL = 60.0
INTERVALLE_SANS_TACHE = 3600.0


@pytest.fixture(scope="module")
def redis_url() -> Iterator[str]:
    conteneur = (
        DockerContainer(IMAGE_REDIS)
        .with_exposed_ports(6379)
        .waiting_for(LogMessageWaitStrategy("Ready to accept connections"))
    )
    with conteneur:
        # Sous Windows, « localhost » passe d'abord par IPv6 et Docker Desktop coupe la connexion.
        hote = conteneur.get_container_host_ip().replace("localhost", "127.0.0.1")
        yield f"redis://{hote}:{conteneur.get_exposed_port(6379)}/0"


class ObservateurRedis:
    def __init__(self, url: str) -> None:
        self.url = url

    def _client(self) -> Redis:
        return Redis.from_url(self.url, decode_responses=True, socket_timeout=10)

    async def vider(self) -> None:
        async with self._client() as client:
            await client.flushdb()

    async def membres(self, cle: str) -> list[str]:
        async with self._client() as client:
            return list(await client.zrange(cle, 0, -1))

    async def cles(self, motif: str) -> list[str]:
        async with self._client() as client:
            return sorted([cle async for cle in client.scan_iter(match=motif)])


@pytest.fixture
async def observateur(redis_url: str) -> ObservateurRedis:
    acces = ObservateurRedis(redis_url)
    await acces.vider()
    return acces


@dataclass
class FileDeTest:
    app: FastAPI
    client: httpx.AsyncClient
    emetteur: EmetteurDeTest
    seance_id: uuid.UUID
    cle: str
    parametres: Parametres

    def entetes(self, sub: str, roles: tuple[str, ...] = ("customer",)) -> dict[str, str]:
        return self.emetteur.entetes(sujet=sub, roles=list(roles))

    async def entrer(self, sub: str, seance_id: uuid.UUID | None = None) -> httpx.Response:
        return await self.client.post(
            f"{ROUTE_FILES}/{seance_id or self.seance_id}/position", headers=self.entetes(sub)
        )

    async def lire(self, sub: str, seance_id: uuid.UUID | None = None) -> httpx.Response:
        return await self.client.get(
            f"{ROUTE_FILES}/{seance_id or self.seance_id}/position", headers=self.entetes(sub)
        )

    def tache(
        self,
        *,
        file: FileRedis | None = None,
        instance: str = "file-attente-1",
        taille: int | None = None,
        intervalle: float | None = None,
        duree_admission: int | None = None,
    ) -> TacheVagues:
        """Tâche des vagues sur la vraie file Redis (celle de l'application par défaut)."""
        return TacheVagues(
            file or self.app.state.file,
            self.parametres.seances_sous_file,
            instance=instance,
            taille=taille or self.parametres.taille_vague,
            intervalle=intervalle or self.parametres.intervalle_vagues,
            duree_admission=duree_admission or self.parametres.duree_admission,
        )


@pytest.fixture
def demarrer_file(
    redis_url: str, observateur: ObservateurRedis
) -> Callable[..., AbstractAsyncContextManager[FileDeTest]]:
    @asynccontextmanager
    async def demarrer(**reglages: Any) -> AsyncIterator[FileDeTest]:
        seance_id = reglages.pop("seance_id", None) or uuid.uuid4()
        cle = reglages.pop("cle", None) or secrets.token_urlsafe(32)
        complets: dict[str, Any] = {
            "instance": "file-attente-1",
            "consul_actif": False,
            "redis_url": redis_url,
            "seances_sous_file": frozenset({seance_id}),
            "admission_cle_signature": cle,
            "intervalle_vagues": INTERVALLE_SANS_TACHE,
            **reglages,
        }
        parametres = Parametres(**complets)
        emetteur = EmetteurDeTest()
        app = creer_app(parametres, verificateur_jetons=emetteur.verificateur())
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                timeout=DELAI_APPEL,
            ) as client,
        ):
            yield FileDeTest(app, client, emetteur, seance_id, cle, parametres)

    return demarrer


@pytest.fixture
async def salle(
    demarrer_file: Callable[..., AbstractAsyncContextManager[FileDeTest]],
) -> AsyncIterator[FileDeTest]:
    """File d'une séance, vagues de 2 clients ; tâche de fond inerte (intervalle d'une heure)."""
    async with demarrer_file(taille_vague=2) as demarree:
        yield demarree
