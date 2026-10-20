"""Métriques Prometheus et traces OpenTelemetry d'un service, en une ligne.

    installer_observabilite(app, "echo")      # à la création de l'application
    instrumenter_moteur(moteur)               # dans le lifespan, une fois le moteur créé

- `/metrics` : métriques Prometheus du processus, dont `http_server_duree_secondes` (histogramme
  par service, méthode, route et statut) et la jauge des disjoncteurs (commun.http). Prometheus
  trouve les instances dans Consul (commun.registre les annonce).
- Traces : FastAPI, httpx et SQLAlchemy sont instrumentés. Le contexte W3C `traceparent` posé
  par Traefik est repris : une requête se suit de la gateway jusqu'à la base. Export OTLP vers
  `OTEL_EXPORTER_OTLP_ENDPOINT` (Tempo) ; sans cette variable, aucune trace n'est exportée.
- `/health` et `/metrics`, appelés en boucle par Consul et Prometheus, ne sont ni tracés ni
  comptés.
"""

import os
import time

from fastapi import FastAPI, Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import SERVICE_INSTANCE_ID, SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Histogram, generate_latest
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.types import ASGIApp, Message, Receive, Scope, Send

ROUTES_TECHNIQUES = ("/health", "/metrics")

DUREE_REQUETES = Histogram(
    "http_server_duree_secondes",
    "Durée de traitement des requêtes HTTP, par service, méthode, route et statut.",
    ["service", "methode", "route", "statut"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


class MiddlewareMetriques:
    """Mesure chaque requête ; la route est le modèle (`/api/v1/echos/{message}`), pas le
    chemin reçu, pour garder un nombre de séries borné."""

    def __init__(self, app: ASGIApp, service: str) -> None:
        self.app = app
        self.service = service

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in ROUTES_TECHNIQUES:
            await self.app(scope, receive, send)
            return

        statut = 500
        debut = time.perf_counter()

        async def envoyer(message: Message) -> None:
            nonlocal statut
            if message["type"] == "http.response.start":
                statut = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, envoyer)
        finally:
            route = scope.get("route")
            DUREE_REQUETES.labels(
                service=self.service,
                methode=scope["method"],
                route=getattr(route, "path", "inconnue"),
                statut=str(statut),
            ).observe(time.perf_counter() - debut)


def _configurer_traces(service: str) -> None:
    """Fournisseur de traces du processus, défini une seule fois (OpenTelemetry l'impose)."""
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return
    ressource = Resource.create(
        {SERVICE_NAME: service, SERVICE_INSTANCE_ID: os.environ.get("INSTANCE", service)}
    )
    fournisseur = TracerProvider(resource=ressource)
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        # L'exportateur lit lui-même l'adresse dans la variable (et y ajoute /v1/traces).
        fournisseur.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(fournisseur)
    HTTPXClientInstrumentor().instrument()


def installer_observabilite(app: FastAPI, service: str) -> None:
    _configurer_traces(service)
    FastAPIInstrumentor.instrument_app(app, excluded_urls=",".join(ROUTES_TECHNIQUES))
    app.add_middleware(MiddlewareMetriques, service=service)

    @app.get("/metrics", include_in_schema=False)
    async def metriques() -> Response:
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


def instrumenter_moteur(moteur: AsyncEngine) -> None:
    """Chaque requête SQL devient un span, enfant de celui de la requête HTTP.

    L'instrumentation se déclare limitée à SQLAlchemy < 2.1 et se désactive sinon ; elle repose
    sur les événements before/after_cursor_execute, inchangés en 2.1 : on passe outre
    (skip_dep_check), et tests/unit/test_observabilite.py vérifie que les spans SQL existent.
    """
    instrumentation = SQLAlchemyInstrumentor()
    # Instrumenteur unique par processus : un second instrument() serait ignoré. Un nouveau
    # moteur (tests, redémarrage du lifespan) remplace donc le précédent.
    if instrumentation.is_instrumented_by_opentelemetry:
        instrumentation.uninstrument()
    instrumentation.instrument(engine=moteur.sync_engine, skip_dep_check=True)
