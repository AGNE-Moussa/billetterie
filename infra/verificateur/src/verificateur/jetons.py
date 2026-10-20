"""Validation locale d'un JWT du realm : signature, expiration, émetteur et audience."""

from dataclasses import dataclass
from typing import Any

import jwt

from verificateur.cles import CacheCles, CleInconnue

# Keycloak signe en RS256. Fixer la liste empêche « alg: none » et la confusion RS256/HS256.
ALGORITHMES = ["RS256"]
# Tolérance sur exp et iat, pour les petits écarts d'horloge entre conteneurs.
TOLERANCE_SECONDES = 10


class JetonInvalide(Exception):
    """Jeton mal formé, mal signé, d'un autre émetteur ou d'une autre audience."""


class JetonExpire(JetonInvalide):
    """Jeton correct mais dont la date d'expiration est passée."""


@dataclass(frozen=True)
class Identite:
    utilisateur: str
    roles: tuple[str, ...]
    client: str


class Verificateur:
    def __init__(self, cles: CacheCles, emetteur: str, audience: str) -> None:
        self._cles = cles
        self._emetteur = emetteur
        self._audience = audience

    async def verifier(self, jeton: str) -> Identite:
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

        roles = contenu.get("realm_access", {}).get("roles", [])
        return Identite(
            utilisateur=str(contenu["sub"]),
            roles=tuple(str(role) for role in roles),
            client=str(contenu.get("azp", "")),
        )
