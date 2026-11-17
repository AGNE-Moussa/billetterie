"""Moteur SQLAlchemy et tables de billets (docs/modele-donnees.md, migrations 0003 et 0004).

Les tables de messagerie (outbox, messages_traites) viennent de commun.outbox (migration 0002).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from commun.erreurs import ErreurMetier

# Statuts d'un billet (docs/modele-donnees.md).
STATUTS_BILLET = ("EMIS", "ANNULE")


class Base(DeclarativeBase):
    # Clés primaires nommées comme dans la migration 0003 (pk_<table>).
    metadata = MetaData(naming_convention={"pk": "pk_%(table_name)s"})


class PlaceLigne(Base):
    """Place d'une séance ; créée à la réception de ticketing.show.scheduled."""

    __tablename__ = "places"
    __table_args__ = (
        UniqueConstraint("seance_id", "rang", "numero", name="uq_places_seance_rang_numero"),
        # Cible de la clé étrangère composite fk_billets_place.
        UniqueConstraint("seance_id", "id", name="uq_places_seance_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Référence Catalogue (pas de clé étrangère entre services).
    seance_id: Mapped[uuid.UUID]
    rang: Mapped[str] = mapped_column(String(10))
    numero: Mapped[int] = mapped_column(Integer)
    # Référence Catalogue : catégorie tarifée de la séance.
    categorie_id: Mapped[uuid.UUID]


class BilletLigne(Base):
    """Billet émis ; `uq_billets_place` garantit qu'une place n'est vendue qu'une fois."""

    __tablename__ = "billets"
    __table_args__ = (
        UniqueConstraint("seance_id", "place_id", name="uq_billets_place"),
        # Un billet porte la séance de sa place.
        ForeignKeyConstraint(
            ["seance_id", "place_id"],
            ["places.seance_id", "places.id"],
            name="fk_billets_place",
        ),
        CheckConstraint("statut IN ('EMIS', 'ANNULE')", name="ck_billets_statut"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Référence Commandes.
    commande_id: Mapped[uuid.UUID]
    # sub Keycloak de l'acheteur.
    client: Mapped[str] = mapped_column(String(255))
    # Référence Catalogue.
    seance_id: Mapped[uuid.UUID]
    place_id: Mapped[uuid.UUID]
    statut: Mapped[str] = mapped_column(String(10))
    qr_code: Mapped[str] = mapped_column(Text)
    emis_le: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SeanceAnnuleeLigne(Base):
    """Séance annulée (migration 0004) ; consultée à l'émission, l'ordre des messages n'étant
    pas garanti. Remplie par ticketing.show.cancelled (hors BIL-009)."""

    __tablename__ = "seances_annulees"

    # Référence Catalogue.
    seance_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    annulee_le: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BaseIndisponible(ErreurMetier):
    """Base injoignable : 503, sans détail technique (ni URL ni trace) pour le client."""

    def __init__(self) -> None:
        super().__init__(
            "BASE_INDISPONIBLE",
            503,
            "La base de données ne répond pas.",
            titre="Service indisponible",
        )


def creer_moteur(database_url: str, delai: float | None = None) -> AsyncEngine:
    # pool_pre_ping : une connexion coupée (redémarrage de PostgreSQL) est remplacée.
    # timeout (connexion) et command_timeout (requête) bornent l'attente d'une base qui ne
    # répond plus (asyncpg seulement ; SQLite des tests de squelette garde ses valeurs).
    options = (
        {"timeout": delai, "command_timeout": delai}
        if delai is not None and make_url(database_url).get_driver_name() == "asyncpg"
        else {}
    )
    return create_async_engine(database_url, pool_pre_ping=True, connect_args=options)
