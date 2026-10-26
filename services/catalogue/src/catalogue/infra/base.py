"""Moteur SQLAlchemy et base déclarative (aucune table pour l'instant)."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def creer_moteur(database_url: str) -> AsyncEngine:
    # pool_pre_ping : une connexion coupée (redémarrage de PostgreSQL) est remplacée.
    return create_async_engine(database_url, pool_pre_ping=True)
