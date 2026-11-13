"""Moteur SQLAlchemy et tables de notifications (docs/modele-donnees.md, migration 0003).

Les tables de messagerie (outbox, messages_traites) viennent de commun.outbox (migration 0002).
Écart assumé au modèle (H6 de BIL-009) : `destinataires_commande.seance_id` sans clé étrangère
vers `infos_seances`, projection pas encore remplie.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKeyConstraint, MetaData, String, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Longueur maximale d'une adresse e-mail (comme commandes.email).
LONGUEUR_EMAIL = 320


class Base(DeclarativeBase):
    # Clés primaires nommées comme dans la migration 0003 (pk_<table>).
    metadata = MetaData(naming_convention={"pk": "pk_%(table_name)s"})


class DestinataireLigne(Base):
    """Destinataire d'une commande, rempli par ticketing.order.confirmed."""

    __tablename__ = "destinataires_commande"

    # Référence Commandes.
    commande_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    # NULL pour un revendeur : rien à envoyer.
    email: Mapped[str | None] = mapped_column(String(LONGUEUR_EMAIL))
    # Référence Catalogue (H6 : pas de clé étrangère vers infos_seances).
    seance_id: Mapped[uuid.UUID]


class EnvoiLigne(Base):
    """Historique d'envoi : `uq_envois_evenement_commande` interdit un second e-mail (CA3)."""

    __tablename__ = "envois"
    __table_args__ = (
        UniqueConstraint("evenement_id", "commande_id", name="uq_envois_evenement_commande"),
        ForeignKeyConstraint(
            ["commande_id"],
            ["destinataires_commande.commande_id"],
            name="fk_envois_commande",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Identifiant du message déclencheur.
    evenement_id: Mapped[uuid.UUID]
    type_evenement: Mapped[str] = mapped_column(String(200))
    commande_id: Mapped[uuid.UUID]
    destinataire: Mapped[str] = mapped_column(String(LONGUEUR_EMAIL))
    envoye_le: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def creer_moteur(database_url: str) -> AsyncEngine:
    # pool_pre_ping : une connexion coupée (redémarrage de PostgreSQL) est remplacée.
    return create_async_engine(database_url, pool_pre_ping=True)
