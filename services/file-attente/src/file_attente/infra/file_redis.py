"""File d'attente dans Redis (réalisation de `domaine.file.StockageFile`).

Clés d'une séance (étiquette `{<seance>}` : toutes dans le même slot si Redis passe en cluster) :

- `file-attente:{<seance>}:attente` : sorted set, membre `sub`, score le numéro d'arrivée tiré
  de la séquence (strictement croissant : l'ordre d'entrée, sans ex aequo) ;
- `file-attente:{<seance>}:sequence` : compteur `INCR` des arrivées de la séance, incrémenté
  dans le script d'entrée, seulement pour un client absent de la file ;
- `file-attente:{<seance>}:admis:<sub>` : échéance de l'admission (millisecondes Unix), avec
  expiration `PX` de la durée d'admission ; à l'échéance, la clé disparaît et le client n'est
  plus dans la file.

Chaque opération est un script Lua, exécuté atomiquement par Redis : deux requêtes simultanées
du même client ne créent qu'une entrée, et une vague ne perd ni ne double aucun client. Chaque
appel est borné par `delai` secondes, sans nouvelle tentative : Redis injoignable ou trop lent
donne `FileIndisponible` (503).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import anyio
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

from file_attente.domaine.file import EtatStocke, FileIndisponible, StatutFile

# Verrou de la tâche des vagues, partagé par les instances.
CLE_VERROU_VAGUES = "file-attente:tache-vagues"

# KEYS[1] attente, KEYS[2] admission, KEYS[3] séquence ; ARGV[1] sub.
# Un client déjà en file garde son score (donc sa position) ; sinon il reçoit le numéro suivant
# de la séquence, strictement croissant : deux arrivants ne partagent jamais un score.
_ENTRER = """
local admis = redis.call('GET', KEYS[2])
if admis then
  return {'ADMIS', 0, admis}
end
local ajoute = 0
if not redis.call('ZSCORE', KEYS[1], ARGV[1]) then
  local score = redis.call('INCR', KEYS[3])
  ajoute = redis.call('ZADD', KEYS[1], 'NX', score, ARGV[1])
end
local rang = redis.call('ZRANK', KEYS[1], ARGV[1])
return {'EN_ATTENTE', ajoute, rang}
"""

# KEYS[1] attente, KEYS[2] admission ; ARGV[1] sub.
_LIRE = """
local admis = redis.call('GET', KEYS[2])
if admis then
  return {'ADMIS', admis}
end
local rang = redis.call('ZRANK', KEYS[1], ARGV[1])
if not rang then
  return {'ABSENT'}
end
return {'EN_ATTENTE', rang}
"""

# KEYS[1] attente ; ARGV[1] taille, ARGV[2] durée en ms, ARGV[3] préfixe des clés d'admission.
_VAGUE = """
local t = redis.call('TIME')
local duree = tonumber(ARGV[2])
local echeance = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000) + duree
local membres = redis.call('ZPOPMIN', KEYS[1], tonumber(ARGV[1]))
for i = 1, #membres, 2 do
  redis.call('SET', ARGV[3] .. membres[i], echeance, 'PX', duree)
end
return #membres / 2
"""


def _prefixe(seance_id: UUID) -> str:
    return f"file-attente:{{{seance_id}}}"


def cle_attente(seance_id: UUID) -> str:
    return f"{_prefixe(seance_id)}:attente"


def cle_sequence(seance_id: UUID) -> str:
    return f"{_prefixe(seance_id)}:sequence"


def prefixe_admission(seance_id: UUID) -> str:
    return f"{_prefixe(seance_id)}:admis:"


def _echeance(millisecondes: Any) -> datetime:
    return datetime.fromtimestamp(int(millisecondes) / 1000, UTC)


class FileRedis:
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
        self._entrer = self._client.register_script(_ENTRER)
        self._lire = self._client.register_script(_LIRE)
        self._vague = self._client.register_script(_VAGUE)

    async def _appel(self, script: Any, cles: list[str], arguments: list[Any]) -> Any:
        try:
            with anyio.fail_after(self._delai):
                return await script(keys=cles, args=arguments)
        except (RedisError, OSError, TimeoutError) as erreur:
            raise FileIndisponible() from erreur

    async def entrer(self, seance_id: UUID, sub: str) -> tuple[EtatStocke, bool]:
        cles = [cle_attente(seance_id), prefixe_admission(seance_id) + sub, cle_sequence(seance_id)]
        statut, ajoute, valeur = await self._appel(self._entrer, cles, [sub])
        if statut == StatutFile.ADMIS:
            return EtatStocke(StatutFile.ADMIS, admission_expire_le=_echeance(valeur)), False
        return EtatStocke(StatutFile.EN_ATTENTE, rang=int(valeur)), int(ajoute) == 1

    async def lire(self, seance_id: UUID, sub: str) -> EtatStocke | None:
        cles = [cle_attente(seance_id), prefixe_admission(seance_id) + sub]
        resultat = await self._appel(self._lire, cles, [sub])
        if resultat[0] == StatutFile.ADMIS:
            return EtatStocke(StatutFile.ADMIS, admission_expire_le=_echeance(resultat[1]))
        if resultat[0] == StatutFile.EN_ATTENTE:
            return EtatStocke(StatutFile.EN_ATTENTE, rang=int(resultat[1]))
        return None

    async def admettre_vague(self, seance_id: UUID, taille: int, duree_admission: int) -> int:
        """Admet au plus `taille` clients, les premiers entrés ; renvoie le nombre d'admis."""
        resultat = await self._appel(
            self._vague,
            [cle_attente(seance_id)],
            [taille, duree_admission * 1000, prefixe_admission(seance_id)],
        )
        return int(resultat)

    async def prendre_verrou(self, cle: str, proprietaire: str, duree_ms: int) -> bool:
        """`SET NX PX` : vrai si ce propriétaire a obtenu le verrou (jamais relâché, il expire)."""
        try:
            with anyio.fail_after(self._delai):
                pose = await self._client.set(cle, proprietaire, nx=True, px=duree_ms)
        except (RedisError, OSError, TimeoutError) as erreur:
            raise FileIndisponible() from erreur
        return bool(pose)

    async def verifier(self) -> None:
        """Santé : Redis répond à PING, sinon `FileIndisponible`."""
        try:
            with anyio.fail_after(self._delai):
                await self._client.ping()
        except (RedisError, OSError, TimeoutError) as erreur:
            raise FileIndisponible() from erreur

    async def fermer(self) -> None:
        await self._client.aclose()
