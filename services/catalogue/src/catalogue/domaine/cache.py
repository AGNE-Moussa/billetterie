"""Port du cache des lectures du catalogue (BIL-005), sans dépendance à Redis.

`api/cache_lectures.py` ne connaît que ce port ; `infra/cache.py` le réalise avec redis-py et
les tests unitaires avec un double en mémoire.
"""

from typing import Protocol


class CacheIndisponible(Exception):
    """Cache injoignable, lent ou incohérent : l'appelant continue sans cache, jamais de 5xx."""


class CacheCatalogue(Protocol):
    """Stockage clé-valeur à expiration, avec un compteur de génération par famille de listes.

    Les valeurs sont des corps JSON (UTF-8). Chaque méthode lève `CacheIndisponible` si le
    cache ne répond pas.
    """

    async def lire(self, cle: str) -> str | None:
        """Valeur de la clé, ou None si elle est absente ou expirée."""
        ...

    async def ecrire(self, cle: str, valeur: str, duree: float) -> None:
        """Pose la valeur pour `duree` secondes."""
        ...

    async def generation(self, famille: str) -> int:
        """Génération courante de la famille de listes (0 si jamais incrémentée)."""
        ...

    async def nouvelle_generation(self, famille: str) -> int:
        """Incrémente la génération de la famille et renvoie la nouvelle valeur."""
        ...
