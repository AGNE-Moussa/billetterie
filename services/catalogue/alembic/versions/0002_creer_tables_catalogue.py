"""Créer les tables du catalogue (événements, lieux, séances, catégories, rangs) et les tables
de messagerie (outbox, messages_traites, commun.outbox) : catalogue publie
ticketing.show.scheduled (BIL-004).

Révision : 0002
Précédente : 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from commun.outbox import creer_tables_messagerie, supprimer_tables_messagerie

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evenements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("nom", sa.String(200), nullable=False),
        sa.Column("description", sa.String(5000), nullable=False),
        sa.Column(
            "cree_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evenements"),
    )
    op.create_index("ix_evenements_cree_le_id", "evenements", ["cree_le", "id"])

    op.create_table(
        "lieux",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("nom", sa.String(200), nullable=False),
        sa.Column("adresse", sa.String(300), nullable=False),
        sa.Column("ville", sa.String(100), nullable=False),
        sa.Column(
            "cree_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_lieux"),
    )
    op.create_index("ix_lieux_cree_le_id", "lieux", ["cree_le", "id"])

    op.create_table(
        "seances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evenement_id", sa.Uuid(), nullable=False),
        sa.Column("lieu_id", sa.Uuid(), nullable=False),
        sa.Column("debut", sa.DateTime(timezone=True), nullable=False),
        sa.Column("annulee", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "cree_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_seances"),
        sa.ForeignKeyConstraint(
            ["evenement_id"], ["evenements.id"], name="fk_seances_evenement_id"
        ),
        sa.ForeignKeyConstraint(["lieu_id"], ["lieux.id"], name="fk_seances_lieu_id"),
    )
    op.create_index("ix_seances_evenement_id_debut_id", "seances", ["evenement_id", "debut", "id"])
    op.create_index("ix_seances_lieu_id", "seances", ["lieu_id"])

    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("seance_id", sa.Uuid(), nullable=False),
        sa.Column("nom", sa.String(100), nullable=False),
        sa.Column("prix", sa.Integer(), nullable=False),
        # Position dans la séance, à partir de 0 : ordre de la requête (décision I1).
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_categories"),
        sa.ForeignKeyConstraint(["seance_id"], ["seances.id"], name="fk_categories_seance_id"),
        sa.CheckConstraint("prix > 0", name="ck_categories_prix_positif"),
    )
    op.create_index("ix_categories_seance_id", "categories", ["seance_id"])

    op.create_table(
        "rangs",
        sa.Column("seance_id", sa.Uuid(), nullable=False),
        sa.Column("rang", sa.String(10), nullable=False),
        sa.Column("categorie_id", sa.Uuid(), nullable=False),
        sa.Column("nombre_places", sa.Integer(), nullable=False),
        # Position dans la catégorie, à partir de 0 : ordre de la requête (décision I1).
        sa.Column("position", sa.Integer(), nullable=False),
        # Un rang n'appartient qu'à une catégorie de la séance (ROW_ALREADY_ASSIGNED).
        sa.PrimaryKeyConstraint("seance_id", "rang", name="pk_rangs"),
        sa.ForeignKeyConstraint(["seance_id"], ["seances.id"], name="fk_rangs_seance_id"),
        sa.ForeignKeyConstraint(["categorie_id"], ["categories.id"], name="fk_rangs_categorie_id"),
        sa.CheckConstraint("nombre_places >= 1", name="ck_rangs_nombre_places_minimum"),
    )
    op.create_index("ix_rangs_categorie_id", "rangs", ["categorie_id"])

    creer_tables_messagerie()


def downgrade() -> None:
    supprimer_tables_messagerie()
    op.drop_table("rangs")
    op.drop_table("categories")
    op.drop_table("seances")
    op.drop_table("lieux")
    op.drop_table("evenements")
