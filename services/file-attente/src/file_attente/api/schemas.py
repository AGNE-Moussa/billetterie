"""Corps des réponses (contrat services/file-attente/openapi.yaml)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from file_attente.domaine.file import StatutFile


class Sante(BaseModel):
    statut: str = Field(examples=["ok"])


class PositionFile(BaseModel):
    seance_id: UUID
    statut: StatutFile
    position: int | None = Field(
        ge=1, description="Rang dans la file, 1 pour le prochain admis ; null si ADMIS."
    )
    attente_estimee_secondes: int | None = Field(
        ge=0,
        description=(
            "Attente estimée en secondes, d'après la position, la taille et le rythme des"
            " vagues d'admission ; null si ADMIS."
        ),
    )
    jeton_admission: str | None = Field(
        description=(
            "Jeton d'admission signé par file-attente (séance, appelant, expiration), à"
            " transmettre à creerCommande dans l'en-tête X-Admission-Token ; null si"
            " EN_ATTENTE."
        )
    )
    admission_expire_le: datetime | None = Field(
        description="Fin de validité du jeton d'admission ; null si EN_ATTENTE."
    )
