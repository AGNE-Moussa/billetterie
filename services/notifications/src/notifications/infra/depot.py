"""Dépôt SQL des destinataires et de l'historique d'envoi (réalisation de
`domaine.envois.DepotNotifications`), dans la session du consommateur."""

import uuid
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from notifications.domaine.envois import DepotNotifications, Destinataire, Envoi
from notifications.infra.base import DestinataireLigne, EnvoiLigne


class DepotNotificationsSql:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enregistrer_destinataire(self, destinataire: Destinataire) -> None:
        # Commande déjà connue (même message rejoué, autre identifiant, livraisons
        # simultanées) : ignorée, sans erreur ni doublon.
        await self._session.execute(
            insert(DestinataireLigne)
            .values(
                commande_id=destinataire.commande_id,
                email=destinataire.email,
                seance_id=destinataire.seance_id,
            )
            .on_conflict_do_nothing(index_elements=[DestinataireLigne.commande_id])
        )

    async def lire_destinataire(self, commande_id: uuid.UUID) -> Destinataire | None:
        ligne = await self._session.get(DestinataireLigne, commande_id)
        if ligne is None:
            return None
        return Destinataire(
            commande_id=ligne.commande_id, email=ligne.email, seance_id=ligne.seance_id
        )

    async def inscrire_envoi(self, envoi: Envoi) -> bool:
        # Un traitement concurrent du même événement attend le commit du premier sur
        # uq_envois_evenement_commande, puis ne trouve aucune ligne nouvelle.
        resultat = await self._session.execute(
            insert(EnvoiLigne)
            .values(
                id=uuid.uuid4(),
                evenement_id=envoi.evenement_id,
                type_evenement=envoi.type_evenement,
                commande_id=envoi.commande_id,
                destinataire=envoi.destinataire,
                envoye_le=envoi.envoye_le,
            )
            .on_conflict_do_nothing(constraint="uq_envois_evenement_commande")
            .returning(EnvoiLigne.id)
        )
        return resultat.first() is not None

    async def destinataires_de_la_seance(self, seance_id: uuid.UUID) -> list[Destinataire]:
        """Destinataires connus de la séance, par commande (BIL-011)."""
        lignes = await self._session.scalars(
            select(DestinataireLigne)
            .where(DestinataireLigne.seance_id == seance_id)
            .order_by(DestinataireLigne.commande_id)
        )
        return [
            Destinataire(
                commande_id=ligne.commande_id, email=ligne.email, seance_id=ligne.seance_id
            )
            for ligne in lignes.all()
        ]


class DepotAnnulationsSql(DepotNotificationsSql):
    """Réalisation de `domaine.annulations.DepotAnnulations` (BIL-011) : lectures dans la session
    du consommateur ; chaque `transaction()` ouvre une session à part, validée à la sortie du
    bloc, indépendamment de la transaction du message (`messages_traites`)."""

    def __init__(self, session: AsyncSession, sessions: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(session)
        self._sessions = sessions

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[DepotNotifications]:
        async with self._sessions() as session, session.begin():
            yield DepotNotificationsSql(session)

    def transaction(self) -> AbstractAsyncContextManager[DepotNotifications]:
        return self._transaction()
