"""Verrou de la tâche d'expiration dans Redis (réalisation de `domaine.expiration.VerrouTache`).

`SET <clé> <instance> NX PX <durée>` : une seule instance de Commandes exécute un cycle par
fenêtre de période ; le verrou n'est jamais relâché, il expire seul (décision Q1 de BIL-010).
Chaque appel est borné par `delai` secondes, sans nouvelle tentative : Redis injoignable ou trop
lent donne `VerrouTacheIndisponible` (cycle sauté, décision Q2).
"""

import anyio
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

from commandes.domaine.expiration import VerrouTacheIndisponible


class VerrouTacheRedis:
    def __init__(self, url: str, delai: float) -> None:
        self._delai = delai
        # Connexion paresseuse : aucun accès réseau ici, le service démarre sans Redis joignable.
        self._client: Redis = Redis.from_url(
            url,
            socket_timeout=delai,
            socket_connect_timeout=delai,
            retry=Retry(NoBackoff(), 0),
            decode_responses=True,
        )

    async def prendre(self, cle: str, proprietaire: str, duree_ms: int) -> bool:
        try:
            with anyio.fail_after(self._delai):
                pose = await self._client.set(cle, proprietaire, nx=True, px=duree_ms)
        except (RedisError, OSError, TimeoutError) as erreur:
            raise VerrouTacheIndisponible() from erreur
        return bool(pose)

    async def fermer(self) -> None:
        await self._client.aclose()
