"""Envoi SMTP : serveur ouvert (Mailpit) ou relais authentifié (Brevo, démo en ligne).

smtplib.SMTP est remplacé par un faux serveur qui note les échanges : aucun réseau.
"""

from email.message import EmailMessage
from typing import Any

import pytest

from notifications.infra import smtp as module_smtp
from notifications.infra.smtp import EnvoyeurSmtp

pytestmark = pytest.mark.anyio


class FauxServeur:
    echanges: list[str] = []

    def __init__(self, hote: str, port: int, timeout: float) -> None:
        FauxServeur.echanges = [f"connexion {hote}:{port} ({timeout:g} s)"]

    def __enter__(self) -> "FauxServeur":
        return self

    def __exit__(self, *_: Any) -> None:
        FauxServeur.echanges.append("fin")

    def starttls(self, context: Any) -> None:
        FauxServeur.echanges.append(f"starttls verifie={context.check_hostname}")

    def login(self, utilisateur: str, mot_de_passe: str) -> None:
        FauxServeur.echanges.append(f"login {utilisateur} ({len(mot_de_passe)} caractères)")

    def send_message(self, message: EmailMessage) -> None:
        FauxServeur.echanges.append(f"envoi {message['Subject']}")


@pytest.fixture(autouse=True)
def faux_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module_smtp.smtplib, "SMTP", FauxServeur)


def _message() -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "Vos billets"
    message.set_content("Contenu synthétique.")
    return message


async def test_sans_identifiant_l_envoi_se_fait_en_clair_sans_authentification() -> None:
    await EnvoyeurSmtp("mailpit", 1025, 5.0).envoyer(_message())

    assert FauxServeur.echanges == ["connexion mailpit:1025 (5 s)", "envoi Vos billets", "fin"]


async def test_avec_identifiant_l_envoi_passe_en_starttls_verifie_puis_s_authentifie() -> None:
    envoyeur = EnvoyeurSmtp(
        "smtp-relay.exemple.test",
        587,
        5.0,
        utilisateur="relais@exemple.test",
        mot_de_passe="secret-synthetique",
        starttls=True,
    )

    await envoyeur.envoyer(_message())

    assert FauxServeur.echanges == [
        "connexion smtp-relay.exemple.test:587 (5 s)",
        "starttls verifie=True",
        "login relais@exemple.test (18 caractères)",
        "envoi Vos billets",
        "fin",
    ]
