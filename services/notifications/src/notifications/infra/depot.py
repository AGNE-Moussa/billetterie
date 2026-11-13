"""Dépôt SQL des destinataires et de l'historique d'envoi (réalisation de
`domaine.envois.DepotNotifications`), dans la session du consommateur."""

import uuid

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from notifications.domaine.envois import Destinataire, Envoi
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
