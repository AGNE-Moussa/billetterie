"""Assemblage : configuration, journaux, erreurs, authentification, base, consommateurs RabbitMQ
et relais de l'outbox (si `RABBITMQ_URL`), Consul, routes.

Lancement : uvicorn --factory paiements.principal:creer_app
"""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import async_sessionmaker

from commun.auth import installer_auth
from commun.consommateurs import messagerie
from commun.correlation import MiddlewareCorrelation, configurer_journaux
from commun.erreurs import installer_erreurs
from commun.jetons import VerificateurJetons
from commun.observabilite import installer_observabilite, instrumenter_moteur
from commun.outbox import RelaisOutbox
from commun.registre import inscription, tags_sante_traefik, tags_traefik
from paiements.api.routes import routeur_paiements, routeur_sante
from paiements.config import Parametres, parametres
from paiements.consommateurs import abonner_consommateurs
from paiements.infra.base import creer_moteur

NOM_SERVICE = "paiements"
RESSOURCES = ("payments",)


def tags_consul() -> list[str]:
    """Tags Consul de l'instance : routeur standard et routeur de santé ; aucun routeur des
    revendeurs (BIL-012, H1)."""
    return [
        *tags_traefik(NOM_SERVICE, *RESSOURCES),
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
                if config.rabbitmq_url:
                    # Consommateurs ticketing.show.cancelled et ticketing.ticket.rejected, relais
                    # de ticketing.payment.refunded (BIL-011) ; sans URL, aucun.
                    broker = RabbitBroker(config.rabbitmq_url, fail_fast=False)
                    abonner_consommateurs(broker, app.state.sessions)
                    await pile.enter_async_context(messagerie(broker))
                    relais = RelaisOutbox(app.state.sessions, broker)
                    await pile.enter_async_context(relais.en_fond())
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
                yield
        finally:
            await moteur.dispose()
            await verificateur.aclose()

    app = FastAPI(title="Service paiements", version="0.1.0", lifespan=cycle_de_vie)
    app.state.parametres = config
    installer_erreurs(app)
    installer_auth(app, verificateur)
    app.add_middleware(MiddlewareCorrelation)
    installer_observabilite(app, NOM_SERVICE)
    app.include_router(routeur_sante)
    app.include_router(routeur_paiements)
    return app
