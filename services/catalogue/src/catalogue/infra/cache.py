"""Cache Redis des lectures du catalogue (BIL-005).

Le port `CacheCatalogue` (domaine/cache.py) est ce que les routes connaissent ; `CacheRedis`
le réalise avec redis-py (redis.asyncio). Les tests unitaires le remplacent par un double en
mémoire via la dépendance `obtenir_cache`.

Espace de noms Redis du catalogue :

- `catalogue:cache:...` : copies des réponses (fraîche et de secours), toujours posées avec une
  expiration (SET ... PX) ;
- `catalogue:generation:<famille>` : compteur de génération d'une famille de listes, SANS
  expiration. Il est volontairement hors du préfixe `catalogue:cache:` : si un compteur
  expirait, il repartirait de 0 et les anciennes copies de secours de la génération 0, encore
  vivantes jusqu'à 24 h, redeviendraient accessibles (données périmées ressuscitées).
"""

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

# Le port vit dans le domaine ; réexporté ici pour les importations existantes.
from catalogue.domaine.cache import CacheCatalogue, CacheIndisponible

__all__ = ["PREFIXE_GENERATION", "CacheCatalogue", "CacheIndisponible", "CacheRedis"]

PREFIXE_GENERATION = "catalogue:generation:"


class CacheRedis:
    """Réalisation Redis de `CacheCatalogue` ; chaque appel est borné par `delai` secondes.

    Aucune nouvelle tentative côté client : Redis lent ou absent, on passe à la base tout de
    suite plutôt que d'empiler les attentes.
    """

    def __init__(self, url: str, delai: float) -> None:
        # Le client ne se connecte qu'au premier appel : pas d'accès réseau ici.
        self._client: Redis = Redis.from_url(
            url,
            socket_timeout=delai,
            socket_connect_timeout=delai,
            retry=Retry(NoBackoff(), 0),
            decode_responses=True,
        )

    async def _get(self, cle: str) -> str | None:
        try:
            valeur: bytes | str | None = await self._client.get(cle)
        except (RedisError, OSError) as erreur:
            raise CacheIndisponible() from erreur
        # decode_responses=True : redis-py rend déjà du texte ; bytes par sûreté de typage.
        return valeur.decode("utf-8") if isinstance(valeur, bytes) else valeur

    async def lire(self, cle: str) -> str | None:
        return await self._get(cle)

    async def ecrire(self, cle: str, valeur: str, duree: float) -> None:
        try:
            await self._client.set(cle, valeur, px=max(1, round(duree * 1000)))
        except (RedisError, OSError) as erreur:
            raise CacheIndisponible() from erreur

    async def generation(self, famille: str) -> int:
        valeur = await self._get(PREFIXE_GENERATION + famille)
        if valeur is None:
            return 0
        try:
            return int(valeur)
        except ValueError as erreur:
            # Compteur écrit par un autre outil : on se passe du cache plutôt qu'un 500.
            raise CacheIndisponible() from erreur

    async def nouvelle_generation(self, famille: str) -> int:
        try:
            valeur: int = await self._client.incr(PREFIXE_GENERATION + famille)
        except (RedisError, OSError) as erreur:
            raise CacheIndisponible() from erreur
        return valeur

    async def fermer(self) -> None:
        await self._client.aclose()
