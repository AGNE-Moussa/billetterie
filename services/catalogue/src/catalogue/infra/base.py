"""Moteur SQLAlchemy et tables du catalogue (docs/modele-donnees.md, migration 0002).

Les tables de messagerie (outbox, messages_traites) viennent de commun.outbox.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    false,
    func,
)
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from commun.erreurs import ErreurMetier


class Base(DeclarativeBase):
    # Clés primaires nommées comme dans la migration 0002 (pk_<table>).
    metadata = MetaData(naming_convention={"pk": "pk_%(table_name)s"})


class EvenementLigne(Base):
    __tablename__ = "evenements"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    nom: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(5000))
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LieuLigne(Base):
    __tablename__ = "lieux"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    nom: Mapped[str] = mapped_column(String(200))
    adresse: Mapped[str] = mapped_column(String(300))
    ville: Mapped[str] = mapped_column(String(100))
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SeanceLigne(Base):
    __tablename__ = "seances"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    evenement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evenements.id", name="fk_seances_evenement_id")
    )
    lieu_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lieux.id", name="fk_seances_lieu_id"))
    debut: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    annulee: Mapped[bool] = mapped_column(Boolean, server_default=false())
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CategorieLigne(Base):
    __tablename__ = "categories"
    __table_args__ = (CheckConstraint("prix > 0", name="ck_categories_prix_positif"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    seance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seances.id", name="fk_categories_seance_id")
    )
    nom: Mapped[str] = mapped_column(String(100))
    prix: Mapped[int] = mapped_column(Integer)
    # Position dans la séance, à partir de 0 : ordre de la requête (décision I1).
    position: Mapped[int] = mapped_column(Integer)


class RangLigne(Base):
    """Clé (seance_id, rang) : un rang n'appartient qu'à une catégorie de la séance."""

    __tablename__ = "rangs"
    __table_args__ = (CheckConstraint("nombre_places >= 1", name="ck_rangs_nombre_places_minimum"),)

    seance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seances.id", name="fk_rangs_seance_id"), primary_key=True
    )
    rang: Mapped[str] = mapped_column(String(10), primary_key=True)
    categorie_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categories.id", name="fk_rangs_categorie_id")
    )
    nombre_places: Mapped[int] = mapped_column(Integer)
    # Position dans la catégorie, à partir de 0 : ordre de la requête (décision I1).
    position: Mapped[int] = mapped_column(Integer)


# Tris des listes (création puis identifiant ; début puis identifiant) et recherche par séance.
Index("ix_evenements_cree_le_id", EvenementLigne.cree_le, EvenementLigne.id)
Index("ix_lieux_cree_le_id", LieuLigne.cree_le, LieuLigne.id)
Index(
    "ix_seances_evenement_id_debut_id",
    SeanceLigne.evenement_id,
    SeanceLigne.debut,
    SeanceLigne.id,
)
Index("ix_seances_lieu_id", SeanceLigne.lieu_id)
Index("ix_categories_seance_id", CategorieLigne.seance_id)
Index("ix_rangs_categorie_id", RangLigne.categorie_id)


class BaseIndisponible(ErreurMetier):
    """Base injoignable : 503, sans détail technique (ni URL ni trace) pour le client."""

    def __init__(self) -> None:
        super().__init__(
            "BASE_INDISPONIBLE",
            503,
            "La base de données ne répond pas.",
            titre="Service indisponible",
        )


# Voulu : relancée brute, l'erreur serait propagée par Starlette après le 500 générique.
class ErreurBase(ErreurMetier):
    """Erreur imprévue de la base : même réponse que l'erreur générique de commun.erreurs."""

    def __init__(self) -> None:
        super().__init__(
            "ERREUR_INTERNE",
            500,
            "Une erreur inattendue est survenue.",
            titre="Erreur interne",
        )


def creer_moteur(database_url: str, delai: float) -> AsyncEngine:
    # pool_pre_ping : une connexion coupée (redémarrage de PostgreSQL) est remplacée.
    # timeout (connexion) et command_timeout (requête) bornent l'attente d'une base qui ne
    # répond plus : la requête finit en 503 BASE_INDISPONIBLE au lieu de rester bloquée.
    # Options propres au pilote asyncpg (PostgreSQL) ; un autre pilote (SQLite des tests de
    # squelette) garde ses valeurs par défaut.
    options = (
        {"timeout": delai, "command_timeout": delai}
        if make_url(database_url).get_driver_name() == "asyncpg"
        else {}
    )
    return create_async_engine(database_url, pool_pre_ping=True, connect_args=options)
