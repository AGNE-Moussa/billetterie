"""Environnement Alembic asynchrone : l'URL vient de la configuration du service."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from catalogue.config import Parametres
from catalogue.infra.base import Base, creer_moteur
from commun.outbox import METADONNEES_MESSAGERIE

if context.config.config_file_name is not None:
    # Sans disable_existing_loggers=False, fileConfig coupe les journaux déjà créés (commun,
    # application) quand les migrations tournent dans le même processus (tests).
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)

DELAI_MIGRATION = 60.0

# Tables du service et tables communes de messagerie (outbox, messages_traites).
metadonnees = [Base.metadata, METADONNEES_MESSAGERIE]


def _appliquer(connexion: Connection) -> None:
    context.configure(connection=connexion, target_metadata=metadonnees)
    with context.begin_transaction():
        context.run_migrations()


async def _appliquer_en_ligne() -> None:
    # Délai large : une migration peut attendre un verrou plus longtemps qu'une requête d'API.
    moteur = creer_moteur(Parametres().database_url, delai=DELAI_MIGRATION)
    async with moteur.connect() as connexion:
        await connexion.run_sync(_appliquer)
    await moteur.dispose()


if context.is_offline_mode():
    context.configure(url=Parametres().database_url, target_metadata=metadonnees)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_appliquer_en_ligne())
