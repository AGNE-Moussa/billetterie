"""Tâche périodique d'expiration des commandes (BIL-010), démarrée par le lifespan.

Toutes les `periode` secondes, un cycle (`domaine.expiration.executer_cycle`) avec un dépôt
SQL sur une session neuve, le client Paiements de l'application et l'horloge réelle. Arrêtée
proprement à l'arrêt de l'application.

Le premier cycle a lieu une période après le démarrage : les instances qui démarrent ensemble
ne se disputent pas le verrou avant d'être prêtes, et la sûreté reste assurée par la base
(transition sous `FOR UPDATE`).
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commandes.domaine.expiration import VerrouTache, executer_cycle
from commandes.domaine.services import ClientPaiements
from commandes.infra.depot import DepotCommandesSql

journal = logging.getLogger(__name__)


class TacheExpiration:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        verrou: VerrouTache,
        paiements: ClientPaiements,
        *,
        instance: str,
        periode: float,
        lot: int,
    ) -> None:
        self._sessions = sessions
        self._verrou = verrou
        self._paiements = paiements
        self._instance = instance
        self._periode = periode
        self._lot = lot

    async def cycle(self) -> bool:
        """Un cycle immédiat ; vrai si cette instance l'a exécuté (verrou obtenu)."""
        async with self._sessions() as session:
            return await executer_cycle(
                self._verrou,
                DepotCommandesSql(session),
                self._paiements,
                datetime.now(UTC),
                instance=self._instance,
                periode=self._periode,
                lot=self._lot,
            )

    async def _tourner(self) -> None:
        while True:
            await asyncio.sleep(self._periode)
            try:
                await self.cycle()
            except Exception:
                # Base indisponible pour la sélection, par exemple : cycle perdu, la boucle
                # continue (reprise au cycle suivant).
                journal.exception("Cycle de la tâche d'expiration en échec (%s)", self._instance)

    @asynccontextmanager
    async def _en_fond(self) -> AsyncIterator[None]:
        tache = asyncio.create_task(self._tourner(), name="tache-expiration")
        try:
            yield
        finally:
            tache.cancel()
            with suppress(asyncio.CancelledError):
                await tache

    def en_fond(self) -> AbstractAsyncContextManager[None]:
        """Lance la boucle des cycles à l'entrée, l'arrête à la sortie."""
        return self._en_fond()
