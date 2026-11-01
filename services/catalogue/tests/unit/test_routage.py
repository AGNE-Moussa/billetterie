"""Routage Traefik de catalogue : ses trois ressources (CA3, décision Q2 du plan BIL-004)."""

import pytest

from catalogue.principal import NOM_SERVICE, RESSOURCES
from commun.registre import VARIABLE_POINT_ENTREE, tags_sante_traefik, tags_traefik


def test_catalogue_annonce_les_routes_de_ses_ressources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(VARIABLE_POINT_ENTREE, raising=False)

    tags = tags_traefik(NOM_SERVICE, *RESSOURCES)
    sante = tags_sante_traefik(NOM_SERVICE, RESSOURCES[0])

    assert RESSOURCES == ("events", "venues", "shows")
    assert tags == [
        "traefik.enable=true",
        "traefik.http.routers.catalogue.rule=PathPrefix(`/api/v1/events`)"
        " || PathPrefix(`/api/v1/venues`) || PathPrefix(`/api/v1/shows`)",
        "traefik.http.routers.catalogue.entrypoints=web",
        "traefik.http.routers.catalogue.middlewares=standard@file",
    ]
    regles_sante = [t for t in sante if t.startswith("traefik.http.routers.catalogue-sante.rule=")]
    assert len(regles_sante) == 1
    assert "Path(`/api/v1/events/health`)" in regles_sante[0]
