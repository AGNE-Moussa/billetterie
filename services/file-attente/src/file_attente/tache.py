"""Tâche périodique des vagues d'admission (BIL-015), démarrée par le lifespan.

Toutes les `intervalle` secondes, l'instance qui obtient le verrou Redis (`SET NX PX
<intervalle>`, comme la tâche d'expiration de Commandes) admet, pour chaque séance sous file,
au plus `taille` clients par ordre d'entrée. Une seule vague par intervalle, quel que soit le
nombre d'instances. Redis injoignable : le cycle est sauté, la boucle continue.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from uuid import UUID

from file_attente.infra.file_redis import CLE_VERROU_VAGUES, FileRedis

journal = logging.getLogger(__name__)


class TacheVagues:
    def __init__(
        self,
        file: FileRedis,
        seances: frozenset[UUID],
        *,
        instance: str,
        taille: int,
        intervalle: float,
        duree_admission: int,
    ) -> None:
        self._file = file
        self._seances = seances
        self._instance = instance
        self._taille = taille
        self._intervalle = intervalle
        self._duree_admission = duree_admission

    async def cycle(self) -> bool:
        """Une vague immédiate ; vrai si cette instance l'a exécutée (verrou obtenu)."""
        duree_ms = max(1, round(self._intervalle * 1000))
        if not await self._file.prendre_verrou(CLE_VERROU_VAGUES, self._instance, duree_ms):
            return False
        for seance_id in sorted(self._seances):
            admis = await self._file.admettre_vague(seance_id, self._taille, self._duree_admission)
            if admis:
                journal.info("Vague de la séance %s : %d client(s) admis", seance_id, admis)
        return True

    async def _tourner(self) -> None:
        while True:
            await asyncio.sleep(self._intervalle)
            try:
                await self.cycle()
            except Exception:
                journal.exception("Vague d'admission en échec (%s)", self._instance)

    @asynccontextmanager
    async def _en_fond(self) -> AsyncIterator[None]:
        tache = asyncio.create_task(self._tourner(), name="tache-vagues")
        try:
            yield
        finally:
            tache.cancel()
            with suppress(asyncio.CancelledError):
                await tache

    def en_fond(self) -> AbstractAsyncContextManager[None]:
        """Lance la boucle des vagues à l'entrée, l'arrête à la sortie."""
        return self._en_fond()
