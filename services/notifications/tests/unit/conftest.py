"""Fixtures des tests unitaires de notifications : dépôt et envoyeur SMTP en mémoire.

Sans base, ni RabbitMQ, ni SMTP. `DepotEnMemoire` réalise le port `DepotNotifications` ;
`transaction()` rejoue la transaction du consommateur : une exception annule tout ce qui a été
écrit pendant le traitement (comme le rollback de `commun.consommateurs`). `EnvoyeurEnMemoire`
réalise le port `Envoyeur` : il garde chaque message, ou lève l'erreur demandée.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from email.message import EmailMessage
from uuid import UUID

import pytest

from notifications.domaine.envois import Destinataire, Envoi


class DepotEnMemoire:
    def __init__(self) -> None:
        self.destinataires: dict[UUID, Destinataire] = {}
        self.envois: list[Envoi] = []

    def semer_destinataire(self, destinataire: Destinataire) -> None:
        """Pose un destinataire sans passer par le domaine."""
        self.destinataires[destinataire.commande_id] = destinataire

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["DepotEnMemoire"]:
        destinataires, envois = dict(self.destinataires), list(self.envois)
        try:
            yield self
        except BaseException:
            self.destinataires, self.envois = destinataires, envois
            raise

    # --- DepotNotifications ---------------------------------------------------------------------

    async def enregistrer_destinataire(self, destinataire: Destinataire) -> None:
        self.destinataires.setdefault(destinataire.commande_id, destinataire)

    async def lire_destinataire(self, commande_id: UUID) -> Destinataire | None:
        return self.destinataires.get(commande_id)

    # --- annulations.DepotAnnulations (BIL-011) -------------------------------------------------

    async def destinataires_de_la_seance(self, seance_id: UUID) -> list[Destinataire]:
        return [d for d in self.destinataires.values() if d.seance_id == seance_id]

    async def inscrire_envoi(self, envoi: Envoi) -> bool:
        # uq_envois_evenement_commande
        if any(
            (e.evenement_id, e.commande_id) == (envoi.evenement_id, envoi.commande_id)
            for e in self.envois
        ):
            return False
        self.envois.append(envoi)
        return True


class EnvoyeurEnMemoire:
    """`erreur` : levée à chaque appel (OSError, SMTPException) ; `appels` compte les appels."""

    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []
        self.erreur: BaseException | None = None
        self.appels = 0

    async def envoyer(self, message: EmailMessage) -> None:
        self.appels += 1
        if self.erreur is not None:
            raise self.erreur
        self.messages.append(message)


# Le mode importlib de pytest interdit `from conftest import ...` : tout est servi en fixtures.


@pytest.fixture
def depot() -> DepotEnMemoire:
    return DepotEnMemoire()


@pytest.fixture
def envoyeur() -> EnvoyeurEnMemoire:
    return EnvoyeurEnMemoire()
