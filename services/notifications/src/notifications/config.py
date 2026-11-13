"""Configuration du service, lue uniquement dans les variables d'environnement."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Attente maximale d'un échange SMTP, en secondes (décision Q10 de BIL-009).
DELAI_SMTP_PAR_DEFAUT = 5.0
# Expéditeur des e-mails (décision Q9) ; domaine réservé aux tests, aucune adresse réelle.
EXPEDITEUR_PAR_DEFAUT = "billetterie@exemple.test"


class Parametres(BaseSettings):
    model_config = SettingsConfigDict(frozen=True)

    # Exemple : postgresql+asyncpg://notifications:<mot de passe>@postgres:5432/notifications
    database_url: str
    # Nom réseau de l'instance (notifications-1) : adresse annoncée à Consul.
    instance: str = "notifications"
    port: int = 8000
    # Désactivé dans les tests qui n'ont pas de Consul.
    consul_actif: bool = True
    # Broker des événements (ticketing.order.confirmed, ticketing.ticket.issued) ; sans URL,
    # pas de consommateur (tests unitaires).
    # Exemple : amqp://<utilisateur>:<mot de passe>@rabbitmq:5672/
    rabbitmq_url: str | None = None
    # Serveur SMTP (Mailpit en local, BIL-009).
    smtp_hote: str = "mailpit"
    smtp_port: int = 1025
    # Attente maximale d'un envoi, en secondes (> 0) : au-delà, l'envoi échoue et le message
    # est remis en file.
    smtp_delai: float = Field(default=DELAI_SMTP_PAR_DEFAUT, gt=0)
    smtp_expediteur: str = EXPEDITEUR_PAR_DEFAUT
    # Revérification des jetons (commun.auth) : mêmes valeurs que le vérificateur de la gateway.
    jwt_emetteur: str = "http://localhost/auth/realms/billetterie"
    jwt_audience: str = "billetterie-api"
    jwks_url: str = "http://keycloak:8080/auth/realms/billetterie/protocol/openid-connect/certs"


@lru_cache
def parametres() -> Parametres:
    return Parametres()
