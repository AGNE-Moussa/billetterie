"""Créer les tables destinataires_commande et envois (docs/modele-donnees.md, BIL-009).

`uq_envois_evenement_commande` garantit qu'un événement ne produit qu'un e-mail par commande
(CA3, décision Q8) ; `fk_envois_commande` rattache l'envoi au destinataire de la commande.
Écart assumé au modèle (H6) : `destinataires_commande.seance_id` sans clé étrangère vers
`infos_seances`, projection pas encore remplie.

Révision : 0003
Précédente : 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "destinataires_commande",
        sa.Column("commande_id", sa.Uuid(), nullable=False),
        # NULL pour un revendeur : rien à envoyer.
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("seance_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("commande_id", name="pk_destinataires_commande"),
    )

    op.create_table(
        "envois",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evenement_id", sa.Uuid(), nullable=False),
        sa.Column("type_evenement", sa.String(200), nullable=False),
        sa.Column("commande_id", sa.Uuid(), nullable=False),
        sa.Column("destinataire", sa.String(320), nullable=False),
        sa.Column("envoye_le", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_envois"),
        sa.UniqueConstraint("evenement_id", "commande_id", name="uq_envois_evenement_commande"),
        sa.ForeignKeyConstraint(
            ["commande_id"],
            ["destinataires_commande.commande_id"],
            name="fk_envois_commande",
        ),
    )


def downgrade() -> None:
    op.drop_table("envois")
    op.drop_table("destinataires_commande")
