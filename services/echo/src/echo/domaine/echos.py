"""Un echo est un message enregistré une fois, puis relu par n'importe quelle instance."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Echo:
    message: str
    cree_le: datetime


class EchoIntrouvable(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(f"Aucun echo enregistré pour « {message} ».")
        self.message = message


class EchoDejaExistant(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(f"Un echo existe déjà pour « {message} ».")
        self.message = message


class DepotEchos(Protocol):
    """Accès aux echos enregistrés ; l'implémentation vit dans infra/."""

    async def ajouter(self, message: str) -> Echo:
        """Enregistre le message ; lève EchoDejaExistant s'il l'est déjà."""
        ...

    async def trouver(self, message: str) -> Echo | None: ...


async def enregistrer_echo(depot: DepotEchos, message: str) -> Echo:
    return await depot.ajouter(message)


async def lire_echo(depot: DepotEchos, message: str) -> Echo:
    echo = await depot.trouver(message)
    if echo is None:
        raise EchoIntrouvable(message)
    return echo
