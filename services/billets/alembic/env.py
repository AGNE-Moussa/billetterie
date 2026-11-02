"""Environnement Alembic asynchrone : l'URL vient de la configuration du service.

Tables du service et tables communes de messagerie (outbox, messages_traites) : billets
consomme ticketing.show.scheduled (BIL-006). Seule DATABASE_URL est lue (ParametresMigrations) :
la migration ne demande ni Redis ni RabbitMQ.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from billets.config import ParametresMigrations
from billets.infra.base import Base, creer_moteur
from commun.outbox import METADONNEES_MESSAGERIE

if context.config.config_file_name is not None:
    # Sans disable_existing_loggers=False, fileConfig coupe les journaux déjà créés (commun,
    # application) quand les migrations tournent dans le même processus (tests).
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)

metadonnees = [Base.metadata, METADONNEES_MESSAGERIE]


def _appliquer(connexion: Connection) -> None:
    context.configure(connection=connexion, target_metadata=metadonnees)
    with context.begin_transaction():
        context.run_migrations()


async def _appliquer_en_ligne() -> None:
    moteur = creer_moteur(ParametresMigrations().database_url)
    async with moteur.connect() as connexion:
        await connexion.run_sync(_appliquer)
    await moteur.dispose()


if context.is_offline_mode():
    context.configure(url=ParametresMigrations().database_url, target_metadata=metadonnees)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_appliquer_en_ligne())
