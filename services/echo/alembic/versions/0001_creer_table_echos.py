"""Créer la table echos.

Révision : 0001
Précédente :
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "echos",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("message", sa.String(100), nullable=False),
        sa.Column(
            "cree_le",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("message", name="uq_echos_message"),
    )


def downgrade() -> None:
    op.drop_table("echos")
