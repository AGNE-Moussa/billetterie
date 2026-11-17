"""Configuration du service, lue uniquement dans les variables d'environnement."""

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from billets.domaine.qr import LONGUEUR_MIN_CLE

# Délai par défaut d'une connexion et d'une requête à la base, en secondes (comme catalogue).
DELAI_BASE_PAR_DEFAUT = 5.0
# Attente maximale d'un appel à Redis, en secondes (comme catalogue, BIL-005).
DELAI_REDIS_PAR_DEFAUT = 0.5
# Durées du verrou d'une place, en secondes (décision Q8 de BIL-006) : réservation 10 min,
# confirmation 1 h.
DUREE_VERROU_RESERVATION_PAR_DEFAUT = 600
DUREE_VERROU_CONFIRMATION_PAR_DEFAUT = 3600


class ParametresMigrations(BaseSettings):
    """Seule configuration utile à Alembic : la base (ni Redis ni RabbitMQ)."""

    model_config = SettingsConfigDict(frozen=True)

    # Exemple : postgresql+asyncpg://billets:<mot de passe>@postgres:5432/billets
    database_url: str


class Parametres(BaseSettings):
    model_config = SettingsConfigDict(frozen=True)

    # Exemple : postgresql+asyncpg://billets:<mot de passe>@postgres:5432/billets
    database_url: str
    # Nom réseau de l'instance (billets-1, billets-2) : adresse annoncée à Consul.
    instance: str = "billets"
    port: int = 8000
    # Attente maximale d'une connexion ou d'une requête à la base, en secondes : au-delà, la
    # requête répond 503 BASE_INDISPONIBLE.
    delai_base: float = Field(default=DELAI_BASE_PAR_DEFAUT, gt=0)
    # Désactivé dans les tests qui n'ont pas de Consul.
    consul_actif: bool = True
    # Broker des événements (consommateur ticketing.show.scheduled) ; sans URL, pas de
    # consommateur (tests unitaires). Exemple : amqp://<utilisateur>:<mot de passe>@rabbitmq:5672/
    rabbitmq_url: str | None = None
    # Verrous des places, obligatoire (décision Q20 : sans Redis, pas de verrou). Connexion
    # paresseuse : aucun accès réseau au démarrage. Exemple : redis://redis:6379/0
    redis_url: str
    # Attente maximale d'un appel à Redis, en secondes : au-delà, 503 VERROU_INDISPONIBLE.
    delai_redis: float = Field(default=DELAI_REDIS_PAR_DEFAUT, gt=0)
    # Durée d'un verrou de réservation (confirmation à false), en secondes.
    duree_verrou_reservation: int = Field(default=DUREE_VERROU_RESERVATION_PAR_DEFAUT, gt=0)
    # Durée d'un verrou confirmé (confirmation à true), en secondes.
    duree_verrou_confirmation: int = Field(default=DUREE_VERROU_CONFIRMATION_PAR_DEFAUT, gt=0)
    # Clé HMAC du contenu des QR codes (décision Q6 de BIL-009), dans .env, jamais dans le dépôt.
    # Obligatoire, au moins 32 caractères : sans clé, le service ne démarre pas.
    qr_cle_signature: SecretStr

    @field_validator("qr_cle_signature")
    @classmethod
    def _cle_assez_longue(cls, valeur: SecretStr) -> SecretStr:
        if len(valeur.get_secret_value()) < LONGUEUR_MIN_CLE:
            raise ValueError(f"au moins {LONGUEUR_MIN_CLE} caractères")
        return valeur

    # Revérification des jetons (commun.auth) : mêmes valeurs que le vérificateur de la gateway.
    jwt_emetteur: str = "http://localhost/auth/realms/billetterie"
    jwt_audience: str = "billetterie-api"
    jwks_url: str = "http://keycloak:8080/auth/realms/billetterie/protocol/openid-connect/certs"


@lru_cache
def parametres() -> Parametres:
    return Parametres()
