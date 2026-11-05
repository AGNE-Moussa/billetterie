"""Configuration du service, lue uniquement dans les variables d'environnement."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Délai par défaut d'une connexion et d'une requête à la base, en secondes (comme billets).
DELAI_BASE_PAR_DEFAUT = 5.0
# Nombre maximal de billets par client et par séance (décision Q3 de BIL-008).
LIMITE_BILLETS_PAR_SEANCE_PAR_DEFAUT = 10


class ParametresMigrations(BaseSettings):
    """Seule configuration utile à Alembic : la base (ni gateway, ni Keycloak, ni RabbitMQ)."""

    model_config = SettingsConfigDict(frozen=True)

    # Exemple : postgresql+asyncpg://commandes:<mot de passe>@postgres:5432/commandes
    database_url: str


class Parametres(BaseSettings):
    model_config = SettingsConfigDict(frozen=True)

    # Exemple : postgresql+asyncpg://commandes:<mot de passe>@postgres:5432/commandes
    database_url: str
    # Nom réseau de l'instance (commandes-1, commandes-2) : adresse annoncée à Consul.
    instance: str = "commandes"
    port: int = 8000
    # Attente maximale d'une connexion ou d'une requête à la base, en secondes : au-delà, la
    # requête répond 503 BASE_INDISPONIBLE.
    delai_base: float = Field(default=DELAI_BASE_PAR_DEFAUT, gt=0)
    # Désactivé dans les tests qui n'ont pas de Consul.
    consul_actif: bool = True
    # Broker des événements (relais de l'outbox : ticketing.order.confirmed et
    # ticketing.order.expired) ; sans URL, les événements restent dans l'outbox (tests sans
    # RabbitMQ). Exemple : amqp://<utilisateur>:<mot de passe>@rabbitmq:5672/
    rabbitmq_url: str | None = None
    # Gateway par laquelle passent les appels vers Billets, Catalogue et Paiements
    # (commun.http.ClientService, décision Q23 de BIL-008).
    url_gateway: str = "http://traefik"
    # Point de jeton Keycloak du jeton de service (Client Credentials).
    url_jeton: str = "http://keycloak:8080/auth/realms/billetterie/protocol/openid-connect/token"
    # Client Keycloak du jeton de service (scopes seats:lock et payments:write).
    services_client_id: str = "services"
    # Secret de ce client : dans .env (vide dans .env.example), jamais dans le dépôt.
    services_client_secret: SecretStr = SecretStr("")
    # Plafond de billets par client et par séance, lignes EN_ATTENTE et CONFIRMEE comptées.
    limite_billets_par_seance: int = Field(default=LIMITE_BILLETS_PAR_SEANCE_PAR_DEFAUT, gt=0)
    # Revérification des jetons (commun.auth) : mêmes valeurs que le vérificateur de la gateway.
    jwt_emetteur: str = "http://localhost/auth/realms/billetterie"
    jwt_audience: str = "billetterie-api"
    jwks_url: str = "http://keycloak:8080/auth/realms/billetterie/protocol/openid-connect/certs"


@lru_cache
def parametres() -> Parametres:
    return Parametres()
