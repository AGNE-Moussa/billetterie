"""Créer les tables de messagerie : outbox et messages_traites (commun.outbox).

Révision : 0002
Précédente : 0001

Migration type : chaque service qui publie ou consomme des événements reprend ce fichier.
"""

from collections.abc import Sequence

from commun.outbox import creer_tables_messagerie, supprimer_tables_messagerie

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    creer_tables_messagerie()


def downgrade() -> None:
    supprimer_tables_messagerie()
