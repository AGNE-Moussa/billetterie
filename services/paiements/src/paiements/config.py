"""Configuration du service, lue uniquement dans les variables d'environnement."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Délai par défaut d'une connexion et d'une requête à la base, en secondes (comme billets).
DELAI_BASE_PAR_DEFAUT = 5.0


class ParametresMigrations(BaseSettings):
    """Seule configuration utile à Alembic : la base."""

    model_config = SettingsConfigDict(frozen=True)

    # Exemple : postgresql+asyncpg://paiements:<mot de passe>@postgres:5432/paiements
    database_url: str


class Parametres(BaseSettings):
    model_config = SettingsConfigDict(frozen=True)

    # Exemple : postgresql+asyncpg://paiements:<mot de passe>@postgres:5432/paiements
    database_url: str
    # Nom réseau de l'instance (paiements-1) : adresse annoncée à Consul.
    instance: str = "paiements"
    port: int = 8000
    # Attente maximale d'une connexion ou d'une requête à la base, en secondes : au-delà, la
    # requête répond 503 BASE_INDISPONIBLE.
    delai_base: float = Field(default=DELAI_BASE_PAR_DEFAUT, gt=0)
    # Désactivé dans les tests qui n'ont pas de Consul.
    consul_actif: bool = True
    # Revérification des jetons (commun.auth) : mêmes valeurs que le vérificateur de la gateway.
    jwt_emetteur: str = "http://localhost/auth/realms/billetterie"
    jwt_audience: str = "billetterie-api"
    jwks_url: str = "http://keycloak:8080/auth/realms/billetterie/protocol/openid-connect/certs"


@lru_cache
def parametres() -> Parametres:
    return Parametres()
