"""Créer les tables places et billets (docs/modele-donnees.md, décision Q22 de BIL-006).

`uq_billets_place` garantit qu'une place n'est vendue qu'une fois, même si le verrou Redis
échoue ; `fk_billets_place` (`seance_id`, `place_id`) vers `places (seance_id, id)` impose
qu'un billet porte la séance de sa place. La table billets reste vide jusqu'au ticket
d'émission.

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
        "places",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("seance_id", sa.Uuid(), nullable=False),
        sa.Column("rang", sa.String(10), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("categorie_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_places"),
        # Sert aussi l'index de la liste par séance (seance_id en tête).
        sa.UniqueConstraint("seance_id", "rang", "numero", name="uq_places_seance_rang_numero"),
        # Cible de la clé étrangère composite fk_billets_place (seance_id, place_id).
        sa.UniqueConstraint("seance_id", "id", name="uq_places_seance_id"),
    )

    op.create_table(
        "billets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("commande_id", sa.Uuid(), nullable=False),
        sa.Column("client", sa.String(255), nullable=False),
        sa.Column("seance_id", sa.Uuid(), nullable=False),
        sa.Column("place_id", sa.Uuid(), nullable=False),
        sa.Column("statut", sa.String(10), nullable=False),
        sa.Column("qr_code", sa.Text(), nullable=False),
        sa.Column("emis_le", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_billets"),
        # Composite : un billet porte la séance de sa place (review BIL-006, point 3).
        sa.ForeignKeyConstraint(
            ["seance_id", "place_id"],
            ["places.seance_id", "places.id"],
            name="fk_billets_place",
        ),
        sa.UniqueConstraint("seance_id", "place_id", name="uq_billets_place"),
        sa.CheckConstraint("statut IN ('EMIS', 'ANNULE')", name="ck_billets_statut"),
    )


def downgrade() -> None:
    op.drop_table("billets")
    op.drop_table("places")
