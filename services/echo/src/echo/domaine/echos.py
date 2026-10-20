"""Un echo est un message enregistré une fois, puis relu par n'importe quelle instance."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from commun.erreurs import ErreurMetier

# Publié à chaque echo enregistré (voir infra/depot.py).
EVENEMENT_ECHO_CREE = "ticketing.echo.created"


@dataclass(frozen=True)
class Echo:
    message: str
    cree_le: datetime


class EchoIntrouvable(ErreurMetier):
    def __init__(self, message: str) -> None:
        super().__init__(
            "ECHO_INTROUVABLE",
            404,
            f"Aucun echo enregistré pour « {message} ».",
            titre="Echo introuvable",
        )
        self.message = message


class EchoDejaExistant(ErreurMetier):
    def __init__(self, message: str) -> None:
        super().__init__(
            "ECHO_EXISTANT",
            409,
            f"Un echo existe déjà pour « {message} ».",
            titre="Echo déjà existant",
        )
        self.message = message


class DepotEchos(Protocol):
    """Accès aux echos enregistrés ; l'implémentation vit dans infra/."""

    async def ajouter(self, message: str) -> Echo:
        """Enregistre le message et publie EVENEMENT_ECHO_CREE dans la même transaction ;
        lève EchoDejaExistant s'il l'est déjà."""
        ...

    async def trouver(self, message: str) -> Echo | None: ...


async def enregistrer_echo(depot: DepotEchos, message: str) -> Echo:
    return await depot.ajouter(message)


async def lire_echo(depot: DepotEchos, message: str) -> Echo:
    echo = await depot.trouver(message)
    if echo is None:
        raise EchoIntrouvable(message)
    return echo
