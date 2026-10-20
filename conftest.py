"""Fixtures communes à tous les tests du dépôt (racine, services, libs)."""

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Les tests asynchrones (pytest.mark.anyio) tournent sous asyncio."""
    return "asyncio"
