"""Envoi SMTP (réalisation de `domaine.envois.Envoyeur`), borné par `delai` secondes.

smtplib est bloquant : l'envoi tourne dans un fil séparé, jamais dans la boucle asynchrone.
Le délai borne la connexion et chaque lecture du socket (`timeout` de smtplib) ; un serveur
injoignable ou muet lève `OSError` (dont `TimeoutError`).

Aucune adresse e-mail dans les journaux (rules/securite.md) : les exceptions de smtplib
portent les adresses refusées (`SMTPRecipientsRefused`, `SMTPSenderRefused`) ou la réponse
du serveur. Elles sont remplacées par `EnvoiSmtpRefuse`, qui ne garde que le type d'erreur et
le code SMTP, sans chaînage : la trace journalisée par le broker ne les montre pas.
"""

import smtplib
from email.message import EmailMessage

import anyio


class EnvoiSmtpRefuse(smtplib.SMTPException):
    """Refus du serveur SMTP, sans adresse ni réponse brute du serveur."""


def _sans_donnee_personnelle(erreur: smtplib.SMTPException) -> EnvoiSmtpRefuse:
    code = getattr(erreur, "smtp_code", None)
    suffixe = f", code {code}" if isinstance(code, int) else ""
    return EnvoiSmtpRefuse(f"Envoi SMTP refusé ({type(erreur).__name__}{suffixe})")


class EnvoyeurSmtp:
    def __init__(self, hote: str, port: int, delai: float) -> None:
        self._hote = hote
        self._port = port
        self._delai = delai

    def _envoyer_bloquant(self, message: EmailMessage) -> None:
        try:
            with smtplib.SMTP(self._hote, self._port, timeout=self._delai) as serveur:
                serveur.send_message(message)
        except smtplib.SMTPException as erreur:
            raise _sans_donnee_personnelle(erreur) from None

    async def envoyer(self, message: EmailMessage) -> None:
        # abandon_on_cancel : une annulation (arrêt du service) n'attend pas le fil bloqué ;
        # celui-ci se termine de lui-même au plus tard après le délai du socket.
        await anyio.to_thread.run_sync(self._envoyer_bloquant, message, abandon_on_cancel=True)
