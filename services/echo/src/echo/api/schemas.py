"""Corps des requêtes et des réponses."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

Message = Annotated[str, Field(min_length=1, max_length=100, examples=["bonjour"])]


class EchoCreation(BaseModel):
    message: Message


class EchoReponse(BaseModel):
    message: str
    instance: str = Field(description="Instance qui a traité la requête.")
    cree_le: datetime


class Sante(BaseModel):
    statut: str = Field(examples=["ok"])
