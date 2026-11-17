"""Indexer commandes sur (statut, expire_le) pour la tâche d'expiration (BIL-010).

`ix_commandes_statut_expire_le` sert la sélection périodique des commandes EN_ATTENTE dont
`expire_le <= maintenant`, par `expire_le` croissant (décisions Q4 et Q5 du plan BIL-010).

Révision : 0004
Précédente : 0003
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_commandes_statut_expire_le", "commandes", ["statut", "expire_le"])


def downgrade() -> None:
    op.drop_index("ix_commandes_statut_expire_le", table_name="commandes")
