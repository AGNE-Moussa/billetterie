"""Configuration du service, lue uniquement dans les variables d'environnement."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Délai par défaut d'une connexion et d'une requête à la base, en secondes.
DELAI_BASE_PAR_DEFAUT = 5.0


class Parametres(BaseSettings):
    model_config = SettingsConfigDict(frozen=True)

    # Exemple : postgresql+asyncpg://catalogue:<mot de passe>@postgres:5432/catalogue
    database_url: str
    # Nom réseau de l'instance (catalogue-1) : adresse annoncée à Consul.
    instance: str = "catalogue"
    port: int = 8000
    # Attente maximale d'une connexion ou d'une requête à la base, en secondes : au-delà, la
    # requête répond 503 BASE_INDISPONIBLE.
    delai_base: float = Field(default=DELAI_BASE_PAR_DEFAUT, gt=0)
    # Désactivé dans les tests qui n'ont pas de Consul.
    consul_actif: bool = True
    # Broker des événements (relais de l'outbox) ; sans URL, les événements restent dans
    # l'outbox (tests sans RabbitMQ). Exemple : amqp://<utilisateur>:<mot de passe>@rabbitmq:5672/
    rabbitmq_url: str | None = None
    # Revérification des jetons (commun.auth) : mêmes valeurs que le vérificateur de la gateway.
    jwt_emetteur: str = "http://localhost/auth/realms/billetterie"
    jwt_audience: str = "billetterie-api"
    jwks_url: str = "http://keycloak:8080/auth/realms/billetterie/protocol/openid-connect/certs"


@lru_cache
def parametres() -> Parametres:
    return Parametres()
