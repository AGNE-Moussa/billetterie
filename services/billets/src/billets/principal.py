"""Assemblage : configuration, journaux, erreurs, authentification, base, Consul, verrous Redis,
consommateurs RabbitMQ, routes.

Lancement : uvicorn --factory billets.principal:creer_app
"""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import async_sessionmaker

from billets.api.routes import routeur_places, routeur_sante
from billets.config import Parametres, parametres
from billets.consommateurs import abonner_consommateurs
from billets.infra.base import creer_moteur
from billets.infra.verrous import VerrousRedis
from commun.auth import installer_auth
from commun.consommateurs import messagerie
from commun.correlation import MiddlewareCorrelation, configurer_journaux
from commun.erreurs import installer_erreurs
from commun.jetons import VerificateurJetons
from commun.observabilite import installer_observabilite, instrumenter_moteur
from commun.registre import inscription, tags_sante_traefik, tags_traefik

NOM_SERVICE = "billets"
RESSOURCES = ("seats",)


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
                # Connexion paresseuse : aucun accès réseau au démarrage (décision Q20).
                verrous = VerrousRedis(config.redis_url, config.delai_redis)
                pile.push_async_callback(verrous.fermer)
                app.state.verrous = verrous
                if config.rabbitmq_url:
                    # Consommateur ticketing.show.scheduled (décision Q5) ; sans URL, aucun.
                    broker = RabbitBroker(config.rabbitmq_url, fail_fast=False)
                    abonner_consommateurs(broker, app.state.sessions)
                    await pile.enter_async_context(messagerie(broker))
                if config.consul_actif:
                    # Inscription une fois prêt, retrait avant la fermeture des ressources.
                    await pile.enter_async_context(
                        inscription(
                            NOM_SERVICE,
                            config.instance,
                            config.port,
                            [
                                *tags_traefik(NOM_SERVICE, *RESSOURCES),
                                # GET /api/v1/<ressource>/health réécrit en /health.
                                *tags_sante_traefik(NOM_SERVICE, RESSOURCES[0]),
                            ],
                        )
                    )
                yield
        finally:
            await moteur.dispose()
            await verificateur.aclose()

    app = FastAPI(title="Service billets", version="0.1.0", lifespan=cycle_de_vie)
    app.state.parametres = config
    app.state.verrous = None
    installer_erreurs(app)
    installer_auth(app, verificateur)
    app.add_middleware(MiddlewareCorrelation)
    installer_observabilite(app, NOM_SERVICE)
    app.include_router(routeur_sante)
    app.include_router(routeur_places)
    return app
