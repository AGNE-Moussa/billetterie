"""Assemblage : configuration, journaux, erreurs, authentification, base, Consul, clients des
autres services, relais de l'outbox, routes.

Lancement : uvicorn --factory commandes.principal:creer_app
"""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import async_sessionmaker

from commandes.api.routes import routeur_commandes, routeur_sante
from commandes.config import Parametres, parametres
from commandes.infra.base import creer_moteur, creer_moteur_cles
from commandes.infra.clients import (
    CIBLE_BILLETS,
    CIBLE_CATALOGUE,
    CIBLE_PAIEMENTS,
    ClientBilletsHttp,
    ClientCatalogueHttp,
    ClientPaiementsHttp,
)
from commun.auth import installer_auth
from commun.correlation import MiddlewareCorrelation, configurer_journaux
from commun.erreurs import installer_erreurs
from commun.http import ClientService, JetonService
from commun.jetons import VerificateurJetons
from commun.observabilite import installer_observabilite, instrumenter_moteur
from commun.outbox import RelaisOutbox
from commun.registre import inscription, tags_sante_traefik, tags_traefik

NOM_SERVICE = "commandes"
RESSOURCES = ("orders",)


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
        # Pool séparé pour les clés d'idempotence (review BIL-008, point 4).
        moteur_cles = creer_moteur_cles(config.database_url, config.delai_base)
        app.state.moteur_cles = moteur_cles
        try:
            async with AsyncExitStack() as pile:
                # Jeton de service (Client Credentials), demandé au premier appel sortant.
                jeton = JetonService(
                    config.url_jeton,
                    config.services_client_id,
                    config.services_client_secret.get_secret_value(),
                )
                pile.push_async_callback(jeton.aclose)
                catalogue = ClientService(CIBLE_CATALOGUE, config.url_gateway, jeton=jeton)
                billets = ClientService(CIBLE_BILLETS, config.url_gateway, jeton=jeton)
                paiements = ClientService(CIBLE_PAIEMENTS, config.url_gateway, jeton=jeton)
                for client in (catalogue, billets, paiements):
                    pile.push_async_callback(client.aclose)
                app.state.catalogue = ClientCatalogueHttp(catalogue)
                app.state.billets = ClientBilletsHttp(billets)
                app.state.paiements = ClientPaiementsHttp(paiements)
                if config.consul_actif:
                    # Inscription après l'ouverture de la base, retrait avant sa fermeture.
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
                if config.rabbitmq_url:
                    # Relais de l'outbox : ticketing.order.confirmed et ticketing.order.expired.
                    broker = RabbitBroker(config.rabbitmq_url, fail_fast=False)
                    pile.push_async_callback(broker.stop)
                    relais = RelaisOutbox(app.state.sessions, broker)
                    await pile.enter_async_context(relais.en_fond())
                yield
        finally:
            await moteur_cles.dispose()
            await moteur.dispose()
            await verificateur.aclose()

    app = FastAPI(title="Service commandes", version="0.1.0", lifespan=cycle_de_vie)
    app.state.parametres = config
    # Clients des autres services : créés par le lifespan, remplacés dans les tests.
    app.state.catalogue = None
    app.state.billets = None
    app.state.paiements = None
    installer_erreurs(app)
    installer_auth(app, verificateur)
    app.add_middleware(MiddlewareCorrelation)
    installer_observabilite(app, NOM_SERVICE)
    app.include_router(routeur_sante)
    app.include_router(routeur_commandes)
    return app
