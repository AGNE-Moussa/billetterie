"""Jetons de test signés par une clé RSA de test : simuler n'importe quel appelant sans Keycloak.

    emetteur = EmetteurDeTest()
    installer_auth(app, emetteur.verificateur())
    reponse = await client.post(
        "/api/v1/commandes", headers=emetteur.entetes(roles=["customer"], scopes=["orders:write"])
    )

Réservé aux tests : la clé privée est générée en mémoire à chaque création.
"""

import json
import time
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from commun.jetons import VerificateurJetons

EMETTEUR_TEST = "http://localhost/auth/realms/billetterie"
AUDIENCE_TEST = "billetterie-api"
URL_JWKS_TEST = "http://keycloak-de-test/certs"


class EmetteurDeTest:
    def __init__(
        self,
        emetteur: str = EMETTEUR_TEST,
        audience: str = AUDIENCE_TEST,
        kid: str = "cle-de-test",
    ) -> None:
        self.emetteur = emetteur
        self.audience = audience
        self.kid = kid
        self._cle = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def jeton(
        self,
        *,
        sujet: str = "utilisateur-test",
        roles: list[str] | tuple[str, ...] = (),
        scopes: list[str] | tuple[str, ...] = (),
        client: str = "frontend",
        expire_dans: int = 300,
        **claims: Any,
    ) -> str:
        """Jeton signé ; `claims` remplace ou complète le contenu (iss, aud, exp...)."""
        maintenant = int(time.time())
        contenu: dict[str, Any] = {
            "iss": self.emetteur,
            "aud": [self.audience, "account"],
            "sub": sujet,
            "azp": client,
            "iat": maintenant,
            "exp": maintenant + expire_dans,
            "scope": " ".join(scopes),
            "realm_access": {"roles": list(roles)},
        }
        contenu.update(claims)
        return jwt.encode(contenu, self._cle, algorithm="RS256", headers={"kid": self.kid})

    def entetes(self, **options: Any) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.jeton(**options)}"}

    def jwks(self) -> dict[str, Any]:
        publique: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(self._cle.public_key()))
        return {"keys": [{**publique, "kid": self.kid, "use": "sig", "alg": "RS256"}]}

    def transport(self) -> httpx.MockTransport:
        """Faux Keycloak qui sert le JWKS de la clé de test."""
        return httpx.MockTransport(lambda _requete: httpx.Response(200, json=self.jwks()))

    def verificateur(self) -> VerificateurJetons:
        return VerificateurJetons.depuis_jwks(
            URL_JWKS_TEST, self.emetteur, self.audience, transport=self.transport()
        )
