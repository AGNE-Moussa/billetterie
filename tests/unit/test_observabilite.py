"""Métriques et traces (commun.observabilite), sans Prometheus ni Tempo."""

import logging
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.ext.asyncio import create_async_engine

from commun.correlation import configurer_journaux
from commun.observabilite import installer_observabilite, instrumenter_moteur

pytestmark = pytest.mark.anyio

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
TRACEPARENT = f"00-{TRACE_ID}-00f067aa0ba902b7-01"
journal = logging.getLogger("tests.observabilite")


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/places/{place}")
    async def place(place: str) -> dict[str, str]:
        journal.info("Lecture de la place %s", place)
        return {"place": place}

    @app.get("/health")
    async def sante() -> dict[str, str]:
        return {"statut": "ok"}

    installer_observabilite(app, "essai")
    return app


@pytest.fixture(scope="module")
def spans() -> Iterator[InMemorySpanExporter]:
    """Capte les spans du fournisseur du processus (défini une seule fois)."""
    _app()
    fournisseur = trace.get_tracer_provider()
    assert isinstance(fournisseur, TracerProvider)
    exportateur = InMemorySpanExporter()
    fournisseur.add_span_processor(SimpleSpanProcessor(exportateur))
    yield exportateur
    exportateur.shutdown()


@pytest.fixture
async def client(spans: InMemorySpanExporter) -> AsyncIterator[httpx.AsyncClient]:
    spans.clear()
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _echantillon(texte: str, debut: str) -> float:
    for ligne in texte.splitlines():
        if ligne.startswith(debut):
            return float(ligne.rsplit(" ", 1)[1])
    return 0.0


async def test_les_requetes_sont_mesurees_par_modele_de_route(client: httpx.AsyncClient) -> None:
    serie = (
        'http_server_duree_secondes_count{methode="GET",route="/places/{place}",'
        'service="essai",statut="200"}'
    )
    avant = _echantillon((await client.get("/metrics")).text, serie)

    for place in ("A1", "A2", "B7"):
        await client.get(f"/places/{place}")
    reponse = await client.get("/metrics")

    assert reponse.headers["content-type"].startswith("text/plain")
    assert _echantillon(reponse.text, serie) == avant + 3
    assert 'route="/places/A1"' not in reponse.text  # le modèle, pas le chemin reçu


async def test_sante_et_metriques_ne_sont_ni_comptees_ni_tracees(
    client: httpx.AsyncClient, spans: InMemorySpanExporter
) -> None:
    await client.get("/health")
    reponse = await client.get("/metrics")

    assert 'route="/health"' not in reponse.text
    assert 'route="/metrics"' not in reponse.text
    assert spans.get_finished_spans() == ()


async def test_la_trace_de_la_gateway_est_reprise(
    client: httpx.AsyncClient, spans: InMemorySpanExporter
) -> None:
    await client.get("/places/C3", headers={"traceparent": TRACEPARENT})

    serveur = [s for s in spans.get_finished_spans() if s.kind is trace.SpanKind.SERVER]
    assert len(serveur) == 1
    assert format(serveur[0].context.trace_id, "032x") == TRACE_ID
    assert serveur[0].attributes is not None
    assert serveur[0].attributes["http.route"] == "/places/{place}"
    assert serveur[0].resource.attributes["service.name"] == "essai"


async def test_les_journaux_portent_l_identifiant_de_trace(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    configurer_journaux()
    caplog.set_level(logging.INFO, logger="tests.observabilite")

    await client.get("/places/D4", headers={"traceparent": TRACEPARENT})

    lignes = [r for r in caplog.records if r.name == "tests.observabilite"]
    assert [getattr(r, "trace_id", None) for r in lignes] == [TRACE_ID]


@pytest.mark.parametrize("numero_moteur", [1, 2])
async def test_chaque_requete_sql_est_un_span_enfant_de_la_requete_http(
    spans: InMemorySpanExporter, numero_moteur: int
) -> None:
    """SQLAlchemy 2.1 est instrumenté (malgré la plage déclarée par l'instrumentation), et un
    nouveau moteur l'est aussi (deux passages, deux moteurs distincts)."""
    moteur = create_async_engine("sqlite+aiosqlite:///:memory:")
    instrumenter_moteur(moteur)
    app = FastAPI()

    @app.get("/places")
    async def places() -> dict[str, int]:
        async with moteur.connect() as connexion:
            return {"total": (await connexion.execute(sa.text("SELECT 42"))).scalar_one()}

    installer_observabilite(app, "essai")
    spans.clear()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/places", headers={"traceparent": TRACEPARENT})
    await moteur.dispose()

    termines = spans.get_finished_spans()
    sql = [s for s in termines if s.name.startswith("SELECT")]
    serveur = [s for s in termines if s.kind is trace.SpanKind.SERVER]
    assert len(sql) == 1, [s.name for s in termines]
    assert sql[0].parent is not None
    assert sql[0].context.trace_id == serveur[0].context.trace_id
