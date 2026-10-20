"""Clés publiques du realm (JWKS), gardées en cache : aucun appel à Keycloak par requête.

Les clés sont rechargées quand leur durée de cache est écoulée, ou quand un jeton annonce un
`kid` inconnu (Keycloak a changé de clé). Deux rechargements sont séparés d'au moins
`intervalle_min` secondes : des jetons aux `kid` inventés ne font pas appeler Keycloak en boucle.
Si Keycloak ne répond pas, les clés déjà connues restent utilisées.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from jwt import PyJWK, PyJWKSet
from jwt.exceptions import PyJWKError, PyJWKSetError

journal = logging.getLogger(__name__)


class ClesIndisponibles(Exception):
    """Aucune clé n'a pu être chargée : impossible de vérifier un jeton."""


class CleInconnue(Exception):
    """Le jeton est signé par une clé absente du realm, même après rechargement."""


class CacheCles:
    def __init__(
        self,
        url: str,
        client: httpx.AsyncClient,
        duree: float = 300.0,
        intervalle_min: float = 10.0,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url
        self._client = client
        self._duree = duree
        self._intervalle_min = intervalle_min
        self._horloge = horloge
        self._cles: dict[str, PyJWK] = {}
        self._charge_le: float | None = None
        self._tente_le: float | None = None
        self._verrou = asyncio.Lock()

    async def cle(self, kid: str) -> PyJWK:
        if kid not in self._cles or self._expire():
            async with self._verrou:
                # Une autre requête a pu recharger pendant l'attente du verrou.
                if (kid not in self._cles or self._expire()) and self._rechargement_permis():
                    await self._recharger()
        if not self._cles:
            raise ClesIndisponibles("Clés du realm indisponibles")
        try:
            return self._cles[kid]
        except KeyError:
            raise CleInconnue(kid) from None

    def _expire(self) -> bool:
        return self._charge_le is None or self._horloge() - self._charge_le >= self._duree

    def _rechargement_permis(self) -> bool:
        return self._tente_le is None or self._horloge() - self._tente_le >= self._intervalle_min

    async def _recharger(self) -> None:
        self._tente_le = self._horloge()
        try:
            reponse = await self._client.get(self._url)
            reponse.raise_for_status()
            self._cles = _cles_de_signature(reponse.json())
        except (httpx.HTTPError, ValueError, PyJWKError, PyJWKSetError):
            # On garde les anciennes clés : un Keycloak momentanément absent ne bloque pas tout.
            journal.warning("Rechargement des clés depuis %s impossible", self._url, exc_info=True)
            return
        self._charge_le = self._horloge()
        journal.info("Clés du realm chargées : %s", ", ".join(self._cles))


def _cles_de_signature(jwks: dict[str, Any]) -> dict[str, PyJWK]:
    # Keycloak publie aussi une clé de chiffrement (use=enc) : seules les clés de signature servent.
    signature = [cle for cle in jwks.get("keys", []) if cle.get("use", "sig") == "sig"]
    return {cle.key_id: cle for cle in PyJWKSet(signature).keys if cle.key_id}
