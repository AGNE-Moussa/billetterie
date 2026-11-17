"""Créer la table seances_annulees (docs/modele-donnees.md, décision Q3 de BIL-009).

Consultée à l'émission des billets : une séance annulée ne reçoit aucun billet. Créée vide ;
remplie par le consommateur de ticketing.show.cancelled (hors BIL-009).

Révision : 0004
Précédente : 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "seances_annulees",
        sa.Column("seance_id", sa.Uuid(), nullable=False),
        sa.Column("annulee_le", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("seance_id", name="pk_seances_annulees"),
    )


def downgrade() -> None:
    op.drop_table("seances_annulees")
