"""Configuration du service, lue uniquement dans les variables d'environnement."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Parametres(BaseSettings):
    model_config = SettingsConfigDict(frozen=True)

    # Exemple : postgresql+asyncpg://echo:<mot de passe>@postgres:5432/echo
    database_url: str
    # Nom réseau de l'instance (echo-1, echo-2) : adresse annoncée à Consul.
    instance: str = "echo"
    port: int = 8000
    # Désactivé dans les tests qui n'ont pas de Consul.
    consul_actif: bool = True
    # Revérification des jetons (commun.auth) : mêmes valeurs que le vérificateur de la gateway.
    jwt_emetteur: str = "http://localhost/auth/realms/billetterie"
    jwt_audience: str = "billetterie-api"
    jwks_url: str = "http://keycloak:8080/auth/realms/billetterie/protocol/openid-connect/certs"


@lru_cache
def parametres() -> Parametres:
    return Parametres()
