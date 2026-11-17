"""Assemblage : configuration, journaux, erreurs, authentification, Redis, Consul, tâche des
vagues d'admission, routes.

Écart au modèle echo : ni base PostgreSQL, ni migrations, ni outbox (aucun événement publié) ;
l'état de la file vit dans Redis.

Lancement : uvicorn --factory file_attente.principal:creer_app
"""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

from commun.auth import installer_auth
from commun.correlation import MiddlewareCorrelation, configurer_journaux
from commun.erreurs import installer_erreurs
from commun.jetons import VerificateurJetons
from commun.observabilite import installer_observabilite
from commun.registre import inscription, tags_sante_traefik, tags_traefik
from file_attente.api.routes import routeur_files, routeur_sante
from file_attente.config import Parametres, parametres
from file_attente.infra.file_redis import FileRedis
from file_attente.tache import TacheVagues

NOM_SERVICE = "file-attente"
RESSOURCES = ("queues",)


def tags_consul() -> list[str]:
    """Tags Consul de l'instance : routeur standard et routeur de santé (jeton requis)."""
    return [
        *tags_traefik(NOM_SERVICE, *RESSOURCES),
        # GET /api/v1/queues/health réécrit en /health.
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
        # Connexion paresseuse : le service démarre même si Redis ne répond pas encore.
        file = FileRedis(config.redis_url, config.delai_redis)
        app.state.file = file
        try:
            async with AsyncExitStack() as pile:
                if config.consul_actif:
                    await pile.enter_async_context(
                        inscription(NOM_SERVICE, config.instance, config.port, tags_consul())
                    )
                # Vagues d'admission : une par intervalle, toutes instances confondues (verrou
                # Redis) ; rien à faire si aucune séance n'est sous file.
                if config.seances_sous_file:
                    tache = TacheVagues(
                        file,
                        config.seances_sous_file,
                        instance=config.instance,
                        taille=config.taille_vague,
                        intervalle=config.intervalle_vagues,
                        duree_admission=config.duree_admission,
                    )
                    await pile.enter_async_context(tache.en_fond())
                yield
        finally:
            await file.fermer()
            await verificateur.aclose()

    app = FastAPI(title="Service file-attente", version="0.1.0", lifespan=cycle_de_vie)
    app.state.parametres = config
    # File Redis : créée par le lifespan, remplacée dans les tests.
    app.state.file = None
    installer_erreurs(app)
    installer_auth(app, verificateur)
    app.add_middleware(MiddlewareCorrelation)
    installer_observabilite(app, NOM_SERVICE)
    app.include_router(routeur_sante)
    app.include_router(routeur_files)
    return app
