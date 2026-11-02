"""Verrous des places dans Redis (réalisation de `domaine.verrous.MagasinVerrous`).

Clé `place:<seance_id>:<place_id>`, valeur `commande_id`. Chaque opération qui compare la
valeur avant d'écrire est un script Lua : Redis l'exécute d'un bloc, aucune autre commande ne
peut s'intercaler entre la comparaison et l'écriture (pas de « lire puis écrire »).

Chaque appel est borné par `delai` secondes (connexion, lecture et appel complet), sans
nouvelle tentative côté client : Redis injoignable ou trop lent donne `VerrouIndisponible`
(503), jamais un verrou supposé posé.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import anyio
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

from billets.domaine.verrous import VerrouIndisponible, cle_verrou

# Réponse des scripts quand la commande ne détient pas le verrou.
_REFUS = -1

# KEYS[1] : clé ; ARGV[1] : commande ; ARGV[2] : durée (ms).
# SET NX PX pose le verrou d'une place libre. Sinon, seule la commande qui le détient le
# prolonge, sans jamais raccourcir l'expiration restante (décision Q15). Rend la durée restante
# réellement posée, ou -1.
_POSER = """
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'PX', ARGV[2]) then
  return tonumber(ARGV[2])
end
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
  return -1
end
local duree = tonumber(ARGV[2])
local restant = redis.call('PTTL', KEYS[1])
if restant < duree then
  redis.call('PEXPIRE', KEYS[1], duree)
  return duree
end
return restant
"""

# Repose l'expiration à la durée de confirmation, seulement pour le détenteur ; jamais de
# création de verrou.
_CONFIRMER = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('PEXPIRE', KEYS[1], ARGV[2])
  return tonumber(ARGV[2])
end
return -1
"""

# Compare puis supprime : un ancien détenteur ne supprime jamais le verrou d'une autre commande.
_LIBERER = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class VerrousRedis:
    """Chaque appel est borné par `delai` secondes, sans nouvelle tentative côté client."""

    def __init__(self, url: str, delai: float) -> None:
        self._delai = delai
        # Le client ne se connecte qu'au premier appel : pas d'accès réseau ici.
        self._client: Redis = Redis.from_url(
            url,
            socket_timeout=delai,
            socket_connect_timeout=delai,
            retry=Retry(NoBackoff(), 0),
            decode_responses=True,
        )
        # EVALSHA, avec repli sur EVAL si Redis ne connaît pas encore le script.
        self._poser = self._client.register_script(_POSER)
        self._confirmer = self._client.register_script(_CONFIRMER)
        self._liberer = self._client.register_script(_LIBERER)

    async def _script(self, script: Any, cle: str, *arguments: str | int) -> int:
        try:
            with anyio.fail_after(self._delai):
                reponse = await script(keys=[cle], args=list(arguments))
        except (RedisError, OSError, TimeoutError) as erreur:
            raise VerrouIndisponible() from erreur
        return int(reponse)

    async def poser(
        self, seance_id: UUID, place_id: UUID, commande_id: UUID, duree_ms: int
    ) -> int | None:
        restant = await self._script(
            self._poser, cle_verrou(seance_id, place_id), str(commande_id), duree_ms
        )
        return None if restant == _REFUS else restant

    async def confirmer(
        self, seance_id: UUID, place_id: UUID, commande_id: UUID, duree_ms: int
    ) -> int | None:
        restant = await self._script(
            self._confirmer, cle_verrou(seance_id, place_id), str(commande_id), duree_ms
        )
        return None if restant == _REFUS else restant

    async def liberer(self, seance_id: UUID, place_id: UUID, commande_id: UUID) -> bool:
        supprimees = await self._script(
            self._liberer, cle_verrou(seance_id, place_id), str(commande_id)
        )
        return supprimees == 1

    async def verrouillees(self, seance_id: UUID, place_ids: Sequence[UUID]) -> set[UUID]:
        if not place_ids:
            return set()
        cles = [cle_verrou(seance_id, place_id) for place_id in place_ids]
        try:
            with anyio.fail_after(self._delai):
                valeurs: list[Any] = await self._client.mget(cles)
        except (RedisError, OSError, TimeoutError) as erreur:
            raise VerrouIndisponible() from erreur
        return {
            place_id
            for place_id, valeur in zip(place_ids, valeurs, strict=True)
            if valeur is not None
        }

    async def fermer(self) -> None:
        await self._client.aclose()
