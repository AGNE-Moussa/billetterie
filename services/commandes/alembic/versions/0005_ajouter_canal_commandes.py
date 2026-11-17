"""Ajouter le canal de vente des commandes (BIL-012, décision Q3, question 3 du plan).

Colonne `canal` (`DIRECT` ou `PARTENAIRE`), déduite du rôle du jeton à la création, en base
seulement. Les commandes existantes sont rattachées par leur e-mail : `PARTENAIRE` si `email`
est NULL (revendeur, décision Q22 de BIL-008), `DIRECT` sinon. Puis `NOT NULL`, sans valeur par
défaut (le code fixe toujours le canal), et contrainte `ck_commandes_canal`.

Révision : 0005
Précédente : 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("commandes", sa.Column("canal", sa.String(10), nullable=True))
    op.execute(
        "UPDATE commandes SET canal = CASE WHEN email IS NULL THEN 'PARTENAIRE' ELSE 'DIRECT' END"
    )
    op.alter_column("commandes", "canal", nullable=False)
    op.create_check_constraint(
        "ck_commandes_canal", "commandes", "canal IN ('DIRECT', 'PARTENAIRE')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_commandes_canal", "commandes", type_="check")
    op.drop_column("commandes", "canal")
