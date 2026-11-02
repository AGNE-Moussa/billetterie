"""Configuration du service, lue uniquement dans les variables d'environnement."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Délai par défaut d'une connexion et d'une requête à la base, en secondes.
DELAI_BASE_PAR_DEFAUT = 5.0
# Cache Redis (BIL-005), en secondes : copie fraîche 30 s, copie de secours 24 h (décision D7),
# attente maximale d'un appel à Redis 0,5 s (réponse du développeur à Q5 du plan).
DUREE_FRAICHE_PAR_DEFAUT = 30.0
DUREE_SECOURS_PAR_DEFAUT = 86400.0
DELAI_REDIS_PAR_DEFAUT = 0.5


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
    # Cache Redis des lectures (BIL-005) ; sans URL, pas de cache : les lectures vont en base
    # comme dans BIL-004. Exemple : redis://redis:6379/0
    redis_url: str | None = None
    # Durée de vie de la copie fraîche (cache-aside), en secondes (décision D7 : 30 s).
    cache_duree_fraiche: float = Field(default=DUREE_FRAICHE_PAR_DEFAUT, gt=0)
    # Durée de vie de la copie de secours, lue seulement si la base ne répond pas (D7 : 24 h).
    cache_duree_secours: float = Field(default=DUREE_SECOURS_PAR_DEFAUT, gt=0)
    # Attente maximale d'un appel à Redis, en secondes : au-delà, la lecture continue en base.
    delai_redis: float = Field(default=DELAI_REDIS_PAR_DEFAUT, gt=0)
    # Revérification des jetons (commun.auth) : mêmes valeurs que le vérificateur de la gateway.
    jwt_emetteur: str = "http://localhost/auth/realms/billetterie"
    jwt_audience: str = "billetterie-api"
    jwks_url: str = "http://keycloak:8080/auth/realms/billetterie/protocol/openid-connect/certs"


@lru_cache
def parametres() -> Parametres:
    return Parametres()
