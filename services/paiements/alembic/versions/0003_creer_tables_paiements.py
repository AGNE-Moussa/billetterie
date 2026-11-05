"""Créer les tables paiements et seances_annulees (docs/modele-donnees.md, BIL-008).

`uq_paiements_commande_id` garantit un seul paiement par commande (Idempotency-Key, décision
Q6), même sous des requêtes simultanées ; `ck_paiements_montant` refuse un montant nul ou
négatif. `seances_annulees` est créée vide (décision Q9). Aucune colonne de carte.

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
        "paiements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("commande_id", sa.Uuid(), nullable=False),
        sa.Column("seance_id", sa.Uuid(), nullable=False),
        sa.Column("montant", sa.Integer(), nullable=False),
        sa.Column("statut", sa.String(10), nullable=False),
        sa.Column("cree_le", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_paiements"),
        sa.UniqueConstraint("commande_id", name="uq_paiements_commande_id"),
        sa.CheckConstraint("montant > 0", name="ck_paiements_montant"),
        sa.CheckConstraint(
            "statut IN ('ACCEPTE', 'REFUSE', 'REMBOURSE')", name="ck_paiements_statut"
        ),
    )

    op.create_table(
        "seances_annulees",
        sa.Column("seance_id", sa.Uuid(), nullable=False),
        sa.Column("annulee_le", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("seance_id", name="pk_seances_annulees"),
    )


def downgrade() -> None:
    op.drop_table("seances_annulees")
    op.drop_table("paiements")
