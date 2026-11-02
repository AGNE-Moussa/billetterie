"""Port des verrous de places (Redis), sans dépendance à Redis.

Clé `place:<seance_id>:<place_id>`, valeur `commande_id` (décision Q1 de BIL-006). Les routes
et le domaine ne connaissent que ce port ; `infra/verrous.py` le réalise avec redis-py et les
tests unitaires avec un double en mémoire à horloge contrôlée.
"""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from commun.erreurs import ErreurMetier


class VerrouIndisponible(ErreurMetier):
    """Redis injoignable ou trop lent : verrou ni posé ni lu, 503 (décisions Q9, Q10)."""

    def __init__(self) -> None:
        super().__init__(
            "VERROU_INDISPONIBLE",
            503,
            "Le service de verrouillage des places ne répond pas.",
            titre="Service indisponible",
        )


def cle_verrou(seance_id: UUID, place_id: UUID) -> str:
    """Clé Redis du verrou d'une place."""
    return f"place:{seance_id}:{place_id}"


class MagasinVerrous(Protocol):
    """Verrous à expiration, détenus par une commande.

    Chaque méthode lève `VerrouIndisponible` si le magasin ne répond pas. Les durées sont en
    millisecondes.
    """

    async def poser(
        self, seance_id: UUID, place_id: UUID, commande_id: UUID, duree_ms: int
    ) -> int | None:
        """Pose le verrou pour la commande, ou le prolonge si elle le détient déjà, sans jamais
        raccourcir l'expiration restante (décision Q15).

        Renvoie la durée restante réellement posée (ms), ou None si une autre commande détient
        le verrou.
        """
        ...

    async def confirmer(
        self, seance_id: UUID, place_id: UUID, commande_id: UUID, duree_ms: int
    ) -> int | None:
        """Repose l'expiration du verrou à `duree_ms`, seulement si la commande le détient.

        Renvoie la durée restante (ms), ou None si la commande ne détient pas le verrou.
        """
        ...

    async def liberer(self, seance_id: UUID, place_id: UUID, commande_id: UUID) -> bool:
        """Supprime le verrou seulement si la commande le détient (compare puis supprime).

        Renvoie vrai si un verrou a été supprimé.
        """
        ...

    async def verrouillees(self, seance_id: UUID, place_ids: Sequence[UUID]) -> set[UUID]:
        """Parmi `place_ids`, les places qui portent un verrou (quelle que soit la commande)."""
        ...

    async def fermer(self) -> None:
        """Ferme la connexion au magasin."""
        ...
