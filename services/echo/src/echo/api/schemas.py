"""Corps des requêtes et des réponses."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

from commun.pagination import Page

Message = Annotated[str, Field(min_length=1, max_length=100, examples=["bonjour"])]


class EchoCreation(BaseModel):
    message: Message


class EchoReponse(BaseModel):
    message: str
    instance: str = Field(description="Instance qui a traité la requête.")
    cree_le: datetime


class EchoPage(Page[EchoReponse]):
    total: int = Field(description="Nombre total de messages enregistrés.")


class Sante(BaseModel):
    statut: str = Field(examples=["ok"])
