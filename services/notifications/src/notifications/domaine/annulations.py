"""E-mails d'annulation et de remboursement (BIL-011, CA2) : règles métier, sans SQLAlchemy ni
SMTP.

- `ticketing.show.cancelled` : un e-mail d'annulation par commande de la séance dont le
  destinataire est connu au moment du traitement (Q6, Q7) ; `email` NULL (revendeur) : rien.
- `ticketing.payment.refunded` : un e-mail de remboursement par événement ; commande inconnue :
  `CommandeInconnue` (nouvel essai, puis file d'erreur, Q6).

Anti-doublon par l'historique `envois`, `UNIQUE (evenement_id, commande_id)`, inscrit avant
l'appel SMTP comme pour le billet ; pour l'annulation, une transaction par commande (un échec
SMTP ne fait pas renvoyer l'e-mail aux commandes déjà servies). Les e-mails citent la séance
par son identifiant (H7) ; jamais d'adresse dans les journaux.
"""

import logging
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import Any, Protocol
from uuid import UUID

from commun.evenements import Evenement
from notifications.domaine.envois import (
    CommandeInconnue,
    DepotNotifications,
    Destinataire,
    DonneesInvalides,
    Envoi,
    Envoyeur,
)

journal = logging.getLogger(__name__)

EVENEMENT_SEANCE_ANNULEE = "ticketing.show.cancelled"
EVENEMENT_PAIEMENT_REMBOURSE = "ticketing.payment.refunded"
# Files durables des consommateurs (messages_traites.consommateur, DLQ <nom>.dlq), H5.
CONSOMMATEUR_SEANCE_ANNULEE = "notifications.show-cancelled"
CONSOMMATEUR_PAIEMENT_REMBOURSE = "notifications.payment-refunded"


@dataclass(frozen=True)
class SeanceAnnulee:
    """`data` de ticketing.show.cancelled v1."""

    seance_id: UUID
    evenement_id: UUID


@dataclass(frozen=True)
class PaiementRembourse:
    """`data` de ticketing.payment.refunded v1 ; `montant` en centimes."""

    paiement_id: UUID
    commande_id: UUID
    seance_id: UUID
    montant: int


class DepotAnnulations(DepotNotifications, Protocol):
    """Historique d'envoi et destinataires d'une séance, dans la transaction du consommateur."""

    async def destinataires_de_la_seance(self, seance_id: UUID) -> list[Destinataire]:
        """Destinataires connus des commandes de la séance (revendeurs compris)."""
        ...

    def transaction(self) -> AbstractAsyncContextManager[DepotNotifications]:
        """Transaction propre à une commande, distincte de celle du message : validée à la
        sortie du bloc, annulée si une exception le traverse."""
        ...


def seance_annulee(data: dict[str, Any]) -> SeanceAnnulee:
    """Lit `data` de ticketing.show.cancelled ; lève `DonneesInvalides`."""
    try:
        return SeanceAnnulee(
            seance_id=UUID(str(data["seance_id"])),
            evenement_id=UUID(str(data["evenement_id"])),
        )
    except (KeyError, TypeError, ValueError) as erreur:
        raise DonneesInvalides(f"Séance annulée invalide : {erreur!r}") from erreur


def paiement_rembourse(data: dict[str, Any]) -> PaiementRembourse:
    """Lit `data` de ticketing.payment.refunded ; lève `DonneesInvalides`."""
    try:
        montant = data["montant"]
        if isinstance(montant, bool) or not isinstance(montant, int) or montant <= 0:
            raise ValueError("montant entier positif attendu")
        return PaiementRembourse(
            paiement_id=UUID(str(data["paiement_id"])),
            commande_id=UUID(str(data["commande_id"])),
            seance_id=UUID(str(data["seance_id"])),
            montant=montant,
        )
    except (KeyError, TypeError, ValueError) as erreur:
        raise DonneesInvalides(f"Paiement remboursé invalide : {erreur!r}") from erreur


def montant_en_euros(centimes: int) -> str:
    """9000 → « 90,00 € » (virgule décimale, comme l'affichage du front)."""
    euros, reste = divmod(centimes, 100)
    return f"{euros},{reste:02d} €"


def message_d_annulation(seance_id: UUID, destinataire: str, expediteur: str) -> EmailMessage:
    """E-mail d'annulation de la séance."""
    message = EmailMessage()
    message["Subject"] = "Séance annulée"
    message["From"] = expediteur
    message["To"] = destinataire
    # La séance est citée par son identifiant : `infos_seances` n'est pas remplie (H7).
    message.set_content(
        "Bonjour,\n\n"
        f"La séance {seance_id} pour laquelle vous avez commandé des billets est annulée par "
        "l'organisateur. Vos billets ne sont plus valables.\n\n"
        "Votre paiement vous est remboursé automatiquement ; un e-mail de confirmation du "
        "remboursement suit.\n"
    )
    return message


def message_de_remboursement(
    remboursement: PaiementRembourse, destinataire: str, expediteur: str
) -> EmailMessage:
    """E-mail de remboursement, montant en euros."""
    message = EmailMessage()
    message["Subject"] = "Votre remboursement"
    message["From"] = expediteur
    message["To"] = destinataire
    message.set_content(
        "Bonjour,\n\n"
        f"Votre commande {remboursement.commande_id} (séance {remboursement.seance_id}) est "
        f"remboursée : {montant_en_euros(remboursement.montant)}.\n\n"
        f"Paiement : {remboursement.paiement_id}\n"
    )
    return message


async def envoyer_annulation(
    depot: DepotAnnulations,
    envoyeur: Envoyeur,
    evenement: Evenement,
    *,
    expediteur: str,
    maintenant: datetime,
) -> None:
    """Traitement de ticketing.show.cancelled."""
    annulee = seance_annulee(evenement.data)
    # Destinataires connus au moment du traitement seulement (Q6, limite du README).
    destinataires = await depot.destinataires_de_la_seance(annulee.seance_id)
    if not destinataires:
        journal.info("Séance %s annulée : aucun destinataire connu", annulee.seance_id)
    for destinataire in sorted(destinataires, key=lambda d: str(d.commande_id)):
        if destinataire.email is None:
            journal.info(
                "Séance %s annulée, commande %s : revendeur, aucun e-mail",
                annulee.seance_id,
                destinataire.commande_id,
            )
            continue
        # Une transaction par commande : inscription (une ligne par commande, Q7), envoi SMTP
        # puis commit. Un échec SMTP n'annule que la commande en cours ; au nouvel essai du
        # message, les commandes déjà servies sont inscrites et ne reçoivent rien de plus.
        async with depot.transaction() as transaction:
            nouveau = await transaction.inscrire_envoi(
                Envoi(
                    evenement_id=evenement.id,
                    type_evenement=evenement.type,
                    commande_id=destinataire.commande_id,
                    destinataire=destinataire.email,
                    envoye_le=maintenant,
                )
            )
            if not nouveau:
                journal.info(
                    "E-mail d'annulation de la commande %s déjà envoyé, ignoré",
                    destinataire.commande_id,
                )
                continue
            await envoyeur.envoyer(
                message_d_annulation(annulee.seance_id, destinataire.email, expediteur)
            )
        journal.info(
            "E-mail d'annulation de la séance %s envoyé (commande %s)",
            annulee.seance_id,
            destinataire.commande_id,
        )


async def envoyer_remboursement(
    depot: DepotNotifications,
    envoyeur: Envoyeur,
    evenement: Evenement,
    *,
    expediteur: str,
    maintenant: datetime,
) -> None:
    """Traitement de ticketing.payment.refunded ; lève `CommandeInconnue` si `order.confirmed`
    n'est pas encore reçu."""
    remboursement = paiement_rembourse(evenement.data)
    destinataire = await depot.lire_destinataire(remboursement.commande_id)
    if destinataire is None:
        # Nouvel essai, puis file d'erreur (Q6 ; limite du README pour une commande jamais
        # confirmée).
        raise CommandeInconnue(remboursement.commande_id)
    if destinataire.email is None:
        journal.info(
            "Remboursement de la commande %s : revendeur, aucun e-mail",
            remboursement.commande_id,
        )
        return
    nouveau = await depot.inscrire_envoi(
        Envoi(
            evenement_id=evenement.id,
            type_evenement=evenement.type,
            commande_id=remboursement.commande_id,
            destinataire=destinataire.email,
            envoye_le=maintenant,
        )
    )
    if not nouveau:
        journal.info(
            "E-mail de remboursement de la commande %s déjà envoyé, ignoré",
            remboursement.commande_id,
        )
        return
    await envoyeur.envoyer(message_de_remboursement(remboursement, destinataire.email, expediteur))
    journal.info(
        "E-mail de remboursement envoyé (commande %s, paiement %s)",
        remboursement.commande_id,
        remboursement.paiement_id,
    )
