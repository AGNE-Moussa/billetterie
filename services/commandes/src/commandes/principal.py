"""Assemblage : configuration, journaux, erreurs, authentification, base, Consul, routes.

Lancement : uvicorn --factory commandes.principal:creer_app
"""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from commandes.api.routes import routeur_sante
from commandes.config import Parametres, parametres
from commandes.infra.base import creer_moteur
from commun.auth import installer_auth
from commun.correlation import MiddlewareCorrelation, configurer_journaux
from commun.erreurs import installer_erreurs
from commun.jetons import VerificateurJetons
from commun.observabilite import installer_observabilite, instrumenter_moteur
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
        moteur = creer_moteur(config.database_url)
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

    app = FastAPI(title="Service commandes", version="0.1.0", lifespan=cycle_de_vie)
    app.state.parametres = config
    installer_erreurs(app)
    installer_auth(app, verificateur)
    app.add_middleware(MiddlewareCorrelation)
    installer_observabilite(app, NOM_SERVICE)
    app.include_router(routeur_sante)
    return app
