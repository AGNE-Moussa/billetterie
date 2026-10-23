"""Indexer le tri de la liste des echos : `cree_le` décroissant puis `message` croissant.

Révision : 0003
Précédente : 0002

L'index couvre l'ordre total stable de `GET /api/v1/echos` (`ORDER BY cree_le DESC, message`).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_echos_cree_le_message",
        "echos",
        [sa.text("cree_le DESC"), "message"],
    )


def downgrade() -> None:
    op.drop_index("ix_echos_cree_le_message", table_name="echos")
