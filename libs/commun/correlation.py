"""Identifiant de corrélation d'une requête, et journaux JSON qui le portent.

La gateway pose `X-Correlation-Id` sur chaque requête (plugin correlation de Traefik). Le
middleware le lit, ou en crée un s'il manque ou est invalide, le range dans une `ContextVar` et
le renvoie dans la réponse. Les journaux et les erreurs le lisent avec `correlation_id()`.

Utilisation dans un service :

    configurer_journaux()
    app = FastAPI()
    app.add_middleware(MiddlewareCorrelation)
"""

import json
import logging
import re
import sys
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

ENTETE = "X-Correlation-Id"
# Valeur fournie par le client : bornée, sans espace ni retour à la ligne (pas d'injection
# dans les journaux). Sinon, un nouvel identifiant est créé.
FORMAT_VALIDE = re.compile(r"[A-Za-z0-9._:-]{1,128}")

_correlation: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def correlation_id() -> str | None:
    """Identifiant de la requête en cours ; None hors requête (démarrage, tâches de fond)."""
    return _correlation.get()


@contextmanager
def correlation(identifiant: str | None) -> Iterator[None]:
    """Bloc qui porte l'identifiant d'un message reçu : ses journaux et ses événements le
    reprennent, comme pour une requête HTTP."""
    jeton = _correlation.set(identifiant)
    try:
        yield
    finally:
        _correlation.reset(jeton)


class MiddlewareCorrelation:
    """Middleware ASGI pur : contrairement à BaseHTTPMiddleware, l'application tourne dans le
    même contexte, la ContextVar est donc visible partout pendant la requête."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        recu = dict(scope["headers"]).get(ENTETE.lower().encode(), b"").decode("latin-1")
        identifiant = recu if FORMAT_VALIDE.fullmatch(recu) else str(uuid.uuid4())
        # Pas de reset à la sortie : chaque requête a sa propre copie du contexte (une tâche
        # par requête), et la valeur doit rester lisible par le gestionnaire des erreurs 500
        # et par le journal d'accès d'uvicorn, qui s'exécutent après ce middleware.
        _correlation.set(identifiant)

        async def envoyer(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[ENTETE] = identifiant
            await send(message)

        await self.app(scope, receive, envoyer)


class FormatJson(logging.Formatter):
    """Une ligne JSON par entrée de journal, avec l'identifiant de corrélation."""

    def format(self, record: logging.LogRecord) -> str:
        ligne = {
            "horodatage": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "niveau": record.levelname,
            "journal": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None),
        }
        if record.exc_info:
            ligne["exception"] = self.formatException(record.exc_info)
        return json.dumps(ligne, ensure_ascii=False)


class _GestionnaireJson(logging.StreamHandler):  # type: ignore[type-arg]
    """Marque le gestionnaire installé, pour ne pas l'ajouter deux fois."""


def _fabrique_avec_correlation(
    fabrique: Callable[..., logging.LogRecord],
) -> Callable[..., logging.LogRecord]:
    """L'identifiant est lu à la création de l'entrée, dans le contexte de la requête : un
    gestionnaire qui formate plus tard (file d'attente, tests) le retrouve sur l'entrée."""

    def creer(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = fabrique(*args, **kwargs)
        record.correlation_id = correlation_id()
        return record

    creer.avec_correlation = True  # type: ignore[attr-defined]
    return creer


def configurer_journaux(niveau: int | str = logging.INFO) -> None:
    """Envoie tous les journaux, ceux d'uvicorn compris, en JSON sur la sortie standard."""
    fabrique = logging.getLogRecordFactory()
    if not getattr(fabrique, "avec_correlation", False):
        logging.setLogRecordFactory(_fabrique_avec_correlation(fabrique))
    racine = logging.getLogger()
    racine.setLevel(niveau)
    if not any(isinstance(gestionnaire, _GestionnaireJson) for gestionnaire in racine.handlers):
        gestionnaire = _GestionnaireJson(sys.stdout)
        gestionnaire.setFormatter(FormatJson())
        racine.addHandler(gestionnaire)
    # uvicorn installe ses propres gestionnaires texte : on les retire pour tout recevoir ici.
    for nom in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        journal = logging.getLogger(nom)
        journal.handlers.clear()
        journal.propagate = True
