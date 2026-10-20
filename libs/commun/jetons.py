"""Validation locale des JWT du realm : aucun appel à Keycloak par requête.

Utilisé par le vérificateur de la gateway (infra/verificateur) et par chaque service, qui
revérifie la signature du jeton au lieu de croire les en-têtes (commun.auth).

Les clés publiques du realm (JWKS) sont gardées en cache. Elles sont rechargées quand leur durée
de cache est écoulée, ou quand un jeton annonce un `kid` inconnu (Keycloak a changé de clé).
Deux rechargements sont séparés d'au moins `intervalle_min` secondes : des jetons aux `kid`
inventés ne font pas appeler Keycloak en boucle. Si Keycloak ne répond pas, les clés déjà connues
restent utilisées.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
import jwt
from jwt import PyJWK, PyJWKSet
from jwt.exceptions import PyJWKError, PyJWKSetError

journal = logging.getLogger(__name__)

# Keycloak signe en RS256. Fixer la liste empêche « alg: none » et la confusion RS256/HS256.
ALGORITHMES = ["RS256"]
# Tolérance sur exp et iat, pour les petits écarts d'horloge entre conteneurs.
TOLERANCE_SECONDES = 10
DELAI_APPEL_KEYCLOAK = 5.0


class ClesIndisponibles(Exception):
    """Aucune clé n'a pu être chargée : impossible de vérifier un jeton."""


class CleInconnue(Exception):
    """Le jeton est signé par une clé absente du realm, même après rechargement."""


class JetonInvalide(Exception):
    """Jeton mal formé, mal signé, d'un autre émetteur ou d'une autre audience."""


class JetonExpire(JetonInvalide):
    """Jeton correct mais dont la date d'expiration est passée."""


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


class VerificateurJetons:
    """Vérifie signature, expiration, émetteur et audience ; renvoie le contenu du jeton."""

    def __init__(self, cles: CacheCles, emetteur: str, audience: str) -> None:
        self._cles = cles
        self._emetteur = emetteur
        self._audience = audience

    @classmethod
    def depuis_jwks(
        cls,
        jwks_url: str,
        emetteur: str,
        audience: str,
        *,
        duree_cache: float = 300.0,
        intervalle_min: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> "VerificateurJetons":
        client = httpx.AsyncClient(timeout=DELAI_APPEL_KEYCLOAK, transport=transport)
        cles = CacheCles(jwks_url, client, duree=duree_cache, intervalle_min=intervalle_min)
        verificateur = cls(cles, emetteur, audience)
        verificateur._client = client
        return verificateur

    _client: httpx.AsyncClient | None = None

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def verifier(self, jeton: str) -> dict[str, Any]:
        try:
            kid = jwt.get_unverified_header(jeton).get("kid")
        except jwt.InvalidTokenError as erreur:
            raise JetonInvalide("Jeton mal formé") from erreur
        if not isinstance(kid, str):
            raise JetonInvalide("Jeton sans identifiant de clé (kid)")
        try:
            cle = await self._cles.cle(kid)
        except CleInconnue as erreur:
            raise JetonInvalide("Jeton signé par une clé inconnue") from erreur

        try:
            contenu: dict[str, Any] = jwt.decode(
                jeton,
                cle,
                algorithms=ALGORITHMES,
                audience=self._audience,
                issuer=self._emetteur,
                leeway=TOLERANCE_SECONDES,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as erreur:
            raise JetonExpire("Jeton expiré") from erreur
        except jwt.InvalidTokenError as erreur:
            raise JetonInvalide(str(erreur)) from erreur
        return contenu


def jeton_bearer(autorisation: str | None) -> str | None:
    """Jeton d'un en-tête `Authorization: Bearer ...` ; None pour tout autre schéma."""
    if not autorisation:
        return None
    schema, _, jeton = autorisation.partition(" ")
    if schema.lower() != "bearer":
        return None
    return jeton.strip() or None
