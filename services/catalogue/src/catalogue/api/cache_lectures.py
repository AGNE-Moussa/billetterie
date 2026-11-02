"""Cache-aside des 7 lectures publiques et invalidation après une création (BIL-005).

Pour chaque lecture, deux copies du corps JSON exact de la réponse :

- copie fraîche (`cache_duree_fraiche`, 30 s) : servie sans interroger la base ;
- copie de secours (`cache_duree_secours`, 24 h) : servie, avec `X-Cache-Stale: true`, seulement
  si la base est injoignable (`BaseIndisponible`). Toute autre erreur (404, 422, 500) passe
  telle quelle et rien n'est mis en cache.

Invalidation des listes (questions Q12 à Q14 du plan) : chaque famille de listes a un compteur
de génération, inclus dans la clé. Une création réussie (201, après le commit) l'incrémente :
les anciennes copies, fraîche et de secours, deviennent inaccessibles puis expirent. Une
lecture lit la génération AVANT d'aller en base et n'écrit que sous celle-ci : une lecture
commencée avant une création ne peut donc pas remettre l'ancienne liste sous la nouvelle
génération.

Redis injoignable ou plus lent que `delai_redis` : un seul avertissement journalisé par
requête, au premier échec (sans URL ni secret) ; Redis est alors coupé pour le reste de la
requête, qui continue sans cache. Jamais de 5xx dû à Redis.
"""

import contextlib
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import anyio
from fastapi import Response
from pydantic import BaseModel

from catalogue.domaine.cache import CacheCatalogue, CacheIndisponible
from catalogue.infra.base import BaseIndisponible

# En-tête de la réponse servie depuis la copie de secours (décisions D1 à D4).
EN_TETE_CACHE_PERIME = "X-Cache-Stale"
# Version du format des clés : à changer si le corps mis en cache change de forme.
PREFIXE_CLES = "catalogue:cache:v1:"
TYPE_JSON = "application/json"

# Familles de listes invalidées par les créations (matrice Q13 du plan).
FAMILLE_EVENEMENTS = "evenements"
FAMILLE_LIEUX = "lieux"


def famille_seances(evenement_id: UUID) -> str:
    return f"seances:{evenement_id}"


ValeurParametre = str | int | UUID | datetime | None

journal = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Cles:
    fraiche: str
    secours: str


def _canonique(valeur: str | int | UUID | datetime) -> str | int:
    """Dates en UTC (même instant, même entrée), identifiants en texte, le reste tel quel."""
    if isinstance(valeur, datetime):
        return valeur.astimezone(UTC).isoformat()
    if isinstance(valeur, UUID):
        return str(valeur)
    return valeur


def _empreinte(parametres: dict[str, ValeurParametre]) -> str:
    """SHA-256 du JSON canonique des paramètres validés ; filtres absents omis (Q10)."""
    retenus = {nom: _canonique(v) for nom, v in parametres.items() if v is not None}
    texte = json.dumps(retenus, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def _reponse(corps: str, *, perimee: bool = False) -> Response:
    entetes = {EN_TETE_CACHE_PERIME: "true"} if perimee else None
    return Response(content=corps, media_type=TYPE_JSON, headers=entetes)


class LecturesEnCache:
    """Une instance par requête : après une panne de Redis, la requête n'y retourne plus."""

    def __init__(
        self,
        cache: CacheCatalogue | None,
        delai: float,
        duree_fraiche: float,
        duree_secours: float,
    ) -> None:
        # Cache d'origine, jamais remis à None : distingue « aucun cache configuré » (rien à
        # faire, pas de journal) de « Redis coupé pendant la requête » (`self._cache` à None).
        self._cache_configure = cache
        self._cache = cache
        self._delai = delai
        self._duree_fraiche = duree_fraiche
        self._duree_secours = duree_secours

    async def _borne[T](
        self, appel: Callable[[CacheCatalogue], Awaitable[T]], etape: str | None
    ) -> T:
        """Appel au port borné par `delai_redis` ; échec ou dépassement : CacheIndisponible.

        Seul l'échec réel est journalisé (une fois par requête, `etape` non None) : les appels
        sautés parce que Redis est déjà coupé pour la requête ne journalisent rien.
        """
        cache = self._cache
        if cache is None:
            raise CacheIndisponible()
        try:
            with anyio.fail_after(self._delai):
                return await appel(cache)
        except (TimeoutError, CacheIndisponible) as erreur:
            # Plus aucun appel à Redis pour cette requête : on n'empile pas les attentes.
            self._cache = None
            if etape is not None:
                journal.warning(
                    "Cache Redis injoignable (%s) : la requête continue sans cache.", etape
                )
            raise CacheIndisponible() from erreur

    async def _cles(
        self, operation: str, parametres: dict[str, ValeurParametre], famille: str | None
    ) -> _Cles | None:
        generation = ""
        if famille is not None:
            try:
                numero = await self._borne(
                    lambda cache: cache.generation(famille), "lecture de la génération"
                )
            except CacheIndisponible:
                return None
            generation = f"g{numero}:"
        fin = f"{operation}:{generation}{_empreinte(parametres)}"
        return _Cles(fraiche=f"{PREFIXE_CLES}fraiche:{fin}", secours=f"{PREFIXE_CLES}secours:{fin}")

    async def _lire(self, cle: str, etape: str) -> str | None:
        try:
            return await self._borne(lambda cache: cache.lire(cle), etape)
        except CacheIndisponible:
            return None

    async def _ecrire(self, cle: str, corps: str, duree: float) -> None:
        with contextlib.suppress(CacheIndisponible):
            await self._borne(lambda cache: cache.ecrire(cle, corps, duree), "écriture d'une copie")

    async def servir(
        self,
        operation: str,
        parametres: dict[str, ValeurParametre],
        lire: Callable[[], Awaitable[BaseModel]],
        famille: str | None = None,
    ) -> Response:
        """Réponse 200 de la lecture `operation`, depuis le cache ou la base.

        `famille` : famille de listes dont la génération entre dans la clé (None pour un détail).
        """
        if self._cache is None:
            return _reponse((await lire()).model_dump_json())

        # Génération lue AVANT la lecture en base (Q14).
        cles = await self._cles(operation, parametres, famille)
        if cles is not None:
            fraiche = await self._lire(cles.fraiche, "lecture de la copie fraîche")
            if fraiche is not None:
                # Hit normal, même pendant une panne de la base : pas d'en-tête (D2, Q17).
                return _reponse(fraiche)

        try:
            modele = await lire()
        except BaseIndisponible:
            if cles is not None:
                secours = await self._lire(cles.secours, "lecture de la copie de secours")
                if secours is not None:
                    return _reponse(secours, perimee=True)
            raise

        corps = modele.model_dump_json()
        if cles is not None:
            # Les deux copies ensemble ; le secours repart pour sa durée complète (Q18).
            await self._ecrire(cles.fraiche, corps, self._duree_fraiche)
            await self._ecrire(cles.secours, corps, self._duree_secours)
        return _reponse(corps)

    async def invalider(self, *familles: str) -> None:
        """Après une création commitée (201) : nouvelle génération de chaque famille.

        Redis injoignable : la création reste un succès ; les anciennes copies restent
        servies jusqu'à leur expiration (limite Q6, README du service). Aucun cache configuré
        (pas de `REDIS_URL`) : rien à invalider, donc rien à journaliser.
        """
        if self._cache_configure is None:
            return
        for famille in familles:
            await self._nouvelle_generation(famille)

    async def _nouvelle_generation(self, famille: str) -> None:
        try:
            # Pas d'avertissement générique : l'erreur ci-dessous, propre à l'invalidation, le
            # remplace (une famille non invalidée est une donnée périmée servie, à signaler).
            await self._borne(lambda cache: cache.nouvelle_generation(famille), None)
        except CacheIndisponible:
            journal.error(
                "Cache Redis injoignable : invalidation de la famille %s impossible, des"
                " copies périmées peuvent être servies jusqu'à leur expiration.",
                famille,
            )
