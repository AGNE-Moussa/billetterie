"""Enveloppe commune des événements publiés sur l'exchange topic `ticketing`.

    evenement = Evenement.creer("ticketing.order.confirmed", {"commande_id": str(commande.id)})

Le type sert de clé de routage. `data` est la charge utile, versionnée par `version` : un
changement incompatible crée une version 2, les consommateurs gèrent les deux le temps de la
migration.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from commun.correlation import correlation_id

EXCHANGE = "ticketing"
# Nom au passé : ticketing.<entité>.<fait>, par exemple ticketing.order.confirmed.
FORMAT_TYPE = r"^ticketing\.[a-z][a-z_]*\.[a-z][a-z_]*$"


class Evenement(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    type: str = Field(pattern=FORMAT_TYPE)
    version: int = Field(default=1, ge=1)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str | None = None
    data: dict[str, Any]

    @classmethod
    def creer(cls, type: str, data: dict[str, Any], version: int = 1) -> "Evenement":
        """Événement de la requête en cours : il reprend son identifiant de corrélation."""
        return cls(type=type, version=version, data=data, correlation_id=correlation_id())
