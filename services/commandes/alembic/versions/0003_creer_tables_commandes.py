"""Créer les tables commandes et lignes_commande (docs/modele-donnees.md, BIL-008).

`uq_commandes_client_cle_idempotence` rend l'Idempotency-Key propre à chaque client ;
`ix_commandes_client_seance_id` sert le comptage du plafond de billets (décision Q3). Le
montant d'une ligne et `expire_le` restent NULL tant que le verrou de la place n'a pas répondu
(décision Q13). `paiement_demande` : la commande a déjà été envoyée au moins une fois à
Paiements (review, point 3). Aucune colonne de carte.

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
        "commandes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("cle_idempotence", sa.String(100), nullable=True),
        sa.Column("seance_id", sa.Uuid(), nullable=False),
        sa.Column("statut", sa.String(10), nullable=False),
        sa.Column("montant_total", sa.Integer(), nullable=False),
        sa.Column("cree_le", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expire_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paiement_demande", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id", name="pk_commandes"),
        sa.UniqueConstraint(
            "client", "cle_idempotence", name="uq_commandes_client_cle_idempotence"
        ),
        sa.CheckConstraint(
            "statut IN ('EN_ATTENTE', 'CONFIRMEE', 'EXPIREE', 'REMBOURSEE')",
            name="ck_commandes_statut",
        ),
        sa.CheckConstraint("montant_total >= 0", name="ck_commandes_montant_total"),
    )
    op.create_index("ix_commandes_client_seance_id", "commandes", ["client", "seance_id"])

    op.create_table(
        "lignes_commande",
        sa.Column("commande_id", sa.Uuid(), nullable=False),
        sa.Column("place_id", sa.Uuid(), nullable=False),
        sa.Column("montant", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("commande_id", "place_id", name="pk_lignes_commande"),
        sa.ForeignKeyConstraint(
            ["commande_id"], ["commandes.id"], name="fk_lignes_commande_commande"
        ),
        sa.CheckConstraint("montant > 0", name="ck_lignes_commande_montant"),
    )


def downgrade() -> None:
    op.drop_table("lignes_commande")
    op.drop_index("ix_commandes_client_seance_id", table_name="commandes")
    op.drop_table("commandes")
