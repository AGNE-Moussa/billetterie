"""Moteur SQLAlchemy et tables de paiements (docs/modele-donnees.md, migration 0003).

Les tables de messagerie (outbox, messages_traites) viennent de commun.outbox (migration 0002).
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, MetaData, String, UniqueConstraint
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from commun.erreurs import ErreurMetier


class Base(DeclarativeBase):
    # Clés primaires nommées comme dans la migration 0003 (pk_<table>).
    metadata = MetaData(naming_convention={"pk": "pk_%(table_name)s"})


class PaiementLigne(Base):
    """Paiement simulé d'une commande ; aucune donnée de carte."""

    __tablename__ = "paiements"
    __table_args__ = (
        # Idempotency-Key = commande_id : un seul paiement par commande (décision Q6).
        UniqueConstraint("commande_id", name="uq_paiements_commande_id"),
        CheckConstraint("montant > 0", name="ck_paiements_montant"),
        CheckConstraint("statut IN ('ACCEPTE', 'REFUSE', 'REMBOURSE')", name="ck_paiements_statut"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Référence Commandes.
    commande_id: Mapped[uuid.UUID]
    # Référence Catalogue.
    seance_id: Mapped[uuid.UUID]
    montant: Mapped[int] = mapped_column(Integer)
    statut: Mapped[str] = mapped_column(String(10))
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SeanceAnnuleeLigne(Base):
    """Projection des séances annulées (ticketing.show.cancelled) ; vide en BIL-008 (Q9)."""

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
