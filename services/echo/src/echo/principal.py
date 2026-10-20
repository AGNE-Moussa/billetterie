"""Assemblage : configuration, journaux, erreurs, authentification, base, Consul, relais de
l'outbox, routes.

Lancement : uvicorn --factory echo.principal:creer_app
"""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import async_sessionmaker

from commun.auth import installer_auth
from commun.correlation import MiddlewareCorrelation, configurer_journaux
from commun.erreurs import installer_erreurs
from commun.jetons import VerificateurJetons
from commun.outbox import RelaisOutbox
from commun.registre import inscription, tags_traefik
from echo.api.routes import routeur_echos, routeur_sante
from echo.config import Parametres, parametres
from echo.infra.base import creer_moteur

NOM_SERVICE = "echo"
RESSOURCES = ("echos",)


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
        moteur = creer_moteur(config.database_url)
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
                            tags_traefik(NOM_SERVICE, *RESSOURCES),
                        )
                    )
                if config.rabbitmq_url:
                    # Relais de l'outbox : publie les événements écrits par les requêtes.
                    broker = RabbitBroker(config.rabbitmq_url, fail_fast=False)
                    pile.push_async_callback(broker.stop)
                    relais = RelaisOutbox(app.state.sessions, broker)
                    await pile.enter_async_context(relais.en_fond())
                yield
        finally:
            await moteur.dispose()
            await verificateur.aclose()

    app = FastAPI(title="Service echo", version="0.1.0", lifespan=cycle_de_vie)
    app.state.parametres = config
    installer_erreurs(app)
    installer_auth(app, verificateur)
    app.add_middleware(MiddlewareCorrelation)
    app.include_router(routeur_sante)
    app.include_router(routeur_echos)
    return app
