"""Configuration du service, lue uniquement dans les variables d'environnement.

Pas de base PostgreSQL : toute la file vit dans Redis (BIL-015). `extra="ignore"` : un réglage
inconnu (par exemple `database_url`, passé à chaque service par le test de contrat commun) est
ignoré au lieu d'être refusé.
"""

from functools import lru_cache
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from commun.admission import LONGUEUR_MIN_CLE

# Attente maximale d'un appel à Redis, en secondes (comme billets et commandes).
DELAI_REDIS_PAR_DEFAUT = 0.5
# Clients admis par vague et intervalle entre deux vagues, en secondes.
TAILLE_VAGUE_PAR_DEFAUT = 50
INTERVALLE_VAGUES_PAR_DEFAUT = 10.0
# Durée de validité d'une admission (et de son jeton), en secondes : 10 min (décision BIL-015).
DUREE_ADMISSION_PAR_DEFAUT = 600


def lire_seances(valeur: object) -> object:
    """`SEANCES_SOUS_FILE` : identifiants séparés par des virgules ; vide : aucune séance."""
    if isinstance(valeur, str):
        return frozenset(partie.strip() for partie in valeur.split(",") if partie.strip())
    return valeur


class Parametres(BaseSettings):
    model_config = SettingsConfigDict(frozen=True, extra="ignore")

    # Nom réseau de l'instance (file-attente-1, file-attente-2) : adresse annoncée à Consul.
    instance: str = "file-attente"
    port: int = 8000
    # Désactivé dans les tests qui n'ont pas de Consul.
    consul_actif: bool = True
    # Positions, admissions et verrou de la tâche des vagues. Connexion paresseuse : aucun accès
    # réseau au démarrage. Exemple : redis://redis:6379/0
    redis_url: str = "redis://redis:6379/0"
    # Attente maximale d'un appel à Redis, en secondes : au-delà, 503 FILE_INDISPONIBLE.
    delai_redis: float = Field(default=DELAI_REDIS_PAR_DEFAUT, gt=0)
    # Séances sous file (mêmes valeurs que Commandes) ; hors liste : 404 QUEUE_NOT_FOUND.
    seances_sous_file: Annotated[frozenset[UUID], NoDecode] = frozenset()
    # Clients admis à chaque vague, par ordre d'entrée.
    taille_vague: int = Field(default=TAILLE_VAGUE_PAR_DEFAUT, gt=0)
    # Intervalle entre deux vagues, en secondes (durée du verrou de la tâche des vagues). Au
    # moins 1 ms : Redis refuse PX 0.
    intervalle_vagues: float = Field(default=INTERVALLE_VAGUES_PAR_DEFAUT, ge=0.001)
    # Validité d'une admission, en secondes ; à l'échéance, le client sort de la file.
    duree_admission: int = Field(default=DUREE_ADMISSION_PAR_DEFAUT, gt=0)
    # Clé HMAC des jetons d'admission, partagée avec Commandes ; dans .env, jamais dans le dépôt.
    # Exigée (au moins 32 caractères) dès qu'une séance est sous file.
    admission_cle_signature: SecretStr = SecretStr("")
    # Revérification des jetons (commun.auth) : mêmes valeurs que le vérificateur de la gateway.
    jwt_emetteur: str = "http://localhost/auth/realms/billetterie"
    jwt_audience: str = "billetterie-api"
    jwks_url: str = "http://keycloak:8080/auth/realms/billetterie/protocol/openid-connect/certs"

    @field_validator("seances_sous_file", mode="before")
    @classmethod
    def _lire_seances(cls, valeur: object) -> object:
        return lire_seances(valeur)

    @model_validator(mode="after")
    def _cle_si_file(self) -> Self:
        cle = self.admission_cle_signature.get_secret_value()
        if self.seances_sous_file and len(cle) < LONGUEUR_MIN_CLE:
            raise ValueError(
                f"ADMISSION_CLE_SIGNATURE : au moins {LONGUEUR_MIN_CLE} caractères dès qu'une"
                " séance est sous file"
            )
        return self


@lru_cache
def parametres() -> Parametres:
    return Parametres()
