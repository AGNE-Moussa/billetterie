"""Verrou consultatif PostgreSQL sur une séance, tenu jusqu'à la fin de la transaction (BIL-011).

Ferme les courses entre une écriture qui suppose la séance ouverte (payer, émettre des billets)
et le traitement de `ticketing.show.cancelled` dans le même service (Q2 et Q3 du plan BIL-011) :
partagé pour payer ou émettre, exclusif pour annuler. Chaque service a sa propre base : la clé
n'a besoin d'être stable qu'à l'intérieur d'un service.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def verrouiller_seance(session: AsyncSession, seance_id: UUID, *, exclusif: bool) -> None:
    """`pg_advisory_xact_lock` (exclusif) ou `pg_advisory_xact_lock_shared` (partagé) sur la
    séance, dans la transaction en cours de `session` ; attend que le verrou soit libre."""
    fonction = "pg_advisory_xact_lock" if exclusif else "pg_advisory_xact_lock_shared"
    await session.execute(text(f"SELECT {fonction}(:cle)"), {"cle": cle_seance(seance_id)})


def cle_seance(seance_id: UUID) -> int:
    """Clé `bigint` du verrou : les 64 premiers bits de l'UUID, signés. Deux séances qui
    partageraient ces 64 bits s'attendraient l'une l'autre, sans autre effet."""
    return int.from_bytes(seance_id.bytes[:8], "big", signed=True)
