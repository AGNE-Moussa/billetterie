"""Assemblage de l'application : configuration, base, registre Consul, routes.

Lancement : uvicorn --factory echo.principal:creer_app
"""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from commun.registre import inscription, tags_traefik
from echo.api.erreurs import installer_gestionnaires
from echo.api.routes import routeur_echos, routeur_sante
from echo.config import Parametres, parametres
from echo.infra.base import creer_moteur

NOM_SERVICE = "echo"
RESSOURCES = ("echos",)


def creer_app(config: Parametres | None = None) -> FastAPI:
    config = config or parametres()

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
                yield
        finally:
            await moteur.dispose()

    app = FastAPI(title="Service echo", version="0.1.0", lifespan=cycle_de_vie)
    app.state.parametres = config
    installer_gestionnaires(app)
    app.include_router(routeur_sante)
    app.include_router(routeur_echos)
    return app
