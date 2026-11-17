"""Moteur SQLAlchemy et tables de commandes (docs/modele-donnees.md, migration 0003).

Les tables de messagerie (outbox, messages_traites) viennent de commun.outbox (migration 0002).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    false,
)
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from commun.erreurs import ErreurMetier


class Base(DeclarativeBase):
    # Clés primaires nommées comme dans la migration 0003 (pk_<table>).
    metadata = MetaData(naming_convention={"pk": "pk_%(table_name)s"})


class CommandeLigne(Base):
    """Commande d'un client sur une séance ; aucune donnée de carte."""

    __tablename__ = "commandes"
    __table_args__ = (
        # Idempotency-Key facultatif de creerCommande, propre à chaque client.
        UniqueConstraint("client", "cle_idempotence", name="uq_commandes_client_cle_idempotence"),
        CheckConstraint(
            "statut IN ('EN_ATTENTE', 'CONFIRMEE', 'EXPIREE', 'REMBOURSEE')",
            name="ck_commandes_statut",
        ),
        CheckConstraint("montant_total >= 0", name="ck_commandes_montant_total"),
        # Canal de vente (BIL-012, migration 0005).
        CheckConstraint("canal IN ('DIRECT', 'PARTENAIRE')", name="ck_commandes_canal"),
        # Comptage du plafond de billets par client et par séance (décision Q3).
        Index("ix_commandes_client_seance_id", "client", "seance_id"),
        # Sélection de la tâche d'expiration (BIL-010, migration 0004).
        Index("ix_commandes_statut_expire_le", "statut", "expire_le"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # sub Keycloak de l'appelant.
    client: Mapped[str] = mapped_column(String(255))
    # Claim email du jeton, NULL pour un revendeur (décision Q22).
    email: Mapped[str | None] = mapped_column(String(320))
    cle_idempotence: Mapped[str | None] = mapped_column(String(100))
    # Référence Catalogue (pas de clé étrangère entre services).
    seance_id: Mapped[uuid.UUID]
    statut: Mapped[str] = mapped_column(String(10))
    montant_total: Mapped[int] = mapped_column(Integer)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Fin du plus court des verrous ; NULL tant qu'aucun verrou n'a répondu.
    expire_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Vrai dès que la commande a été envoyée à Paiements (review BIL-008, point 3).
    paiement_demande: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # DIRECT ou PARTENAIRE, déduit du rôle du jeton ; jamais exposé (BIL-012, décision Q3). Sans
    # valeur par défaut : le code le fixe toujours.
    canal: Mapped[str] = mapped_column(String(10))


class LigneCommandeLigne(Base):
    """Place d'une commande et son prix (catégorie de la place au moment de la commande)."""

    __tablename__ = "lignes_commande"
    __table_args__ = (CheckConstraint("montant > 0", name="ck_lignes_commande_montant"),)

    commande_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("commandes.id", name="fk_lignes_commande_commande"), primary_key=True
    )
    # Référence Billets.
    place_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    # Centimes ; NULL tant que le verrou de la place n'a pas répondu (décision Q13).
    montant: Mapped[int | None] = mapped_column(Integer)


class BaseIndisponible(ErreurMetier):
    """Base injoignable : 503, sans détail technique (ni URL ni trace) pour le client."""

    def __init__(self) -> None:
        super().__init__(
            "BASE_INDISPONIBLE",
            503,
            "La base de données ne répond pas.",
            titre="Service indisponible",
        )


# Pool du moteur des clés d'idempotence (review BIL-008, point 4) : chaque connexion est tenue
# pendant toute une requête creerCommande avec clé ; 5 connexions sans débordement (PostgreSQL
# partagé par tous les services), au-delà l'attente est bornée par delai_base.
TAILLE_POOL_CLES = 5
DEBORDEMENT_POOL_CLES = 0


def creer_moteur(
    database_url: str,
    delai: float | None = None,
    *,
    taille_pool: int | None = None,
    debordement_pool: int | None = None,
) -> AsyncEngine:
    # pool_pre_ping : une connexion coupée (redémarrage de PostgreSQL) est remplacée.
    # timeout (connexion) et command_timeout (requête) bornent l'attente d'une base qui ne
    # répond plus, pool_timeout celle d'une connexion libre du pool (asyncpg seulement ;
    # SQLite des tests de squelette garde ses valeurs).
    options: dict[str, Any] = {}
    reglages_pool: dict[str, Any] = {}
    if delai is not None and make_url(database_url).get_driver_name() == "asyncpg":
        options = {"timeout": delai, "command_timeout": delai}
        reglages_pool["pool_timeout"] = delai
        if taille_pool is not None:
            reglages_pool["pool_size"] = taille_pool
        if debordement_pool is not None:
            reglages_pool["max_overflow"] = debordement_pool
    return create_async_engine(
        database_url, pool_pre_ping=True, connect_args=options, **reglages_pool
    )


def creer_moteur_cles(database_url: str, delai: float | None = None) -> AsyncEngine:
    """Moteur dédié aux verrous des clés d'idempotence, séparé de celui des sessions : une
    rafale de requêtes avec clé ne prive jamais les sessions de connexion (review BIL-008,
    point 4)."""
    return creer_moteur(
        database_url,
        delai,
        taille_pool=TAILLE_POOL_CLES,
        debordement_pool=DEBORDEMENT_POOL_CLES,
    )
