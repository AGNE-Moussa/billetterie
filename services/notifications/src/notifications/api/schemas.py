"""Corps des réponses."""

from pydantic import BaseModel, Field


class Sante(BaseModel):
    statut: str = Field(examples=["ok"])
