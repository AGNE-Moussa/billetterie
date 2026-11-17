"""Assemblage : configuration, journaux, erreurs, authentification, base, Consul, relais de
l'outbox, routes.

Lancement : uvicorn --factory catalogue.principal:creer_app
"""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import async_sessionmaker

from catalogue.api.routes import (
    routeur_evenements,
    routeur_lieux,
    routeur_sante,
    routeur_seances,
)
from catalogue.config import Parametres, parametres
from catalogue.infra.base import creer_moteur
from catalogue.infra.cache import CacheRedis
from commun.auth import installer_auth
from commun.correlation import MiddlewareCorrelation, configurer_journaux
from commun.erreurs import installer_erreurs
from commun.jetons import VerificateurJetons
from commun.observabilite import installer_observabilite, instrumenter_moteur
from commun.outbox import RelaisOutbox
from commun.registre import (
    inscription,
    tags_partenaires_traefik,
    tags_sante_traefik,
    tags_traefik,
)

NOM_SERVICE = "catalogue"
# Ressources routées par Traefik vers catalogue (décision Q2 du plan BIL-004) ; la santé reste
# sous la première.
RESSOURCES = ("events", "venues", "shows")


def tags_consul() -> list[str]:
    """Tags Consul de l'instance : routeur standard, routeur des revendeurs sur l'hôte
    partenaires (BIL-012, décision Q1) et routeur de santé."""
    return [
        *tags_traefik(NOM_SERVICE, *RESSOURCES),
        *tags_partenaires_traefik(NOM_SERVICE, *RESSOURCES),
        # GET /api/v1/<ressource>/health réécrit en /health.
        *tags_sante_traefik(NOM_SERVICE, RESSOURCES[0]),
    ]


def creer_app(
    config: Parametres | None = None, verificateur_jetons: VerificateurJetons | None = None
) -> FastAPI:
    """`verificateur_jetons` remplace celui du realm dans les tests (commun.faux_jetons)."""
    config = config or parametres()
    configurer_journaux()
    verificateur = verificateur_jetons or VerificateurJetons.depuis_jwks(
        config.jwks_url, config.jwt_emetteur, config.jwt_audience
    )

    @asynccontextmanager
    async def cycle_de_vie(app: FastAPI) -> AsyncIterator[None]:
        moteur = creer_moteur(config.database_url, config.delai_base)
        instrumenter_moteur(moteur)
        app.state.sessions = async_sessionmaker(moteur, expire_on_commit=False)
        try:
            async with AsyncExitStack() as pile:
                if config.consul_actif:
                    # Inscription après l'ouverture de la base, retrait avant sa fermeture.
                    await pile.enter_async_context(
                        inscription(
                            NOM_SERVICE,
                            config.instance,
                            config.port,
                            tags_consul(),
                        )
                    )
                if config.rabbitmq_url:
                    # Relais de l'outbox : publie ticketing.show.scheduled (décision Q16).
                    broker = RabbitBroker(config.rabbitmq_url, fail_fast=False)
                    pile.push_async_callback(broker.stop)
                    relais = RelaisOutbox(app.state.sessions, broker)
                    await pile.enter_async_context(relais.en_fond())
                if config.redis_url:
                    # Cache des lectures (BIL-005) ; sans URL, app.state.cache reste None.
                    cache = CacheRedis(config.redis_url, config.delai_redis)
                    pile.push_async_callback(cache.fermer)
                    app.state.cache = cache
                yield
        finally:
            await moteur.dispose()
            await verificateur.aclose()

    app = FastAPI(title="Service catalogue", version="0.1.0", lifespan=cycle_de_vie)
    app.state.parametres = config
    app.state.cache = None
    installer_erreurs(app)
    installer_auth(app, verificateur)
    app.add_middleware(MiddlewareCorrelation)
    installer_observabilite(app, NOM_SERVICE)
    app.include_router(routeur_sante)
    app.include_router(routeur_evenements)
    app.include_router(routeur_seances)
    app.include_router(routeur_lieux)
    return app
