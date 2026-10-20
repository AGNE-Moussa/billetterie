"""Configuration du vérificateur, lue uniquement dans les variables d'environnement."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Parametres(BaseSettings):
    model_config = SettingsConfigDict(frozen=True)

    # Émetteur attendu (claim iss), adresse publique du realm :
    # http://localhost/auth/realms/billetterie
    jwt_emetteur: str
    # Audience attendue (claim aud), ajoutée par un mapper du realm.
    jwt_audience: str = "billetterie-api"
    # Clés publiques du realm, adresse interne au réseau Docker :
    # http://keycloak:8080/auth/realms/billetterie/protocol/openid-connect/certs
    jwks_url: str
    # Durée de conservation des clés avant un rechargement, en secondes.
    jwks_duree_cache: float = 300.0
    # Écart minimal entre deux rechargements (protège Keycloak des kid inventés).
    jwks_intervalle_min: float = 10.0
    # Routes accessibles sans jeton, « MÉTHODE /préfixe » séparées par des virgules :
    # GET /api/v1/evenements,GET /api/v1/seances
    routes_publiques: str = ""


@lru_cache
def parametres() -> Parametres:
    return Parametres()
