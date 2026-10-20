"""Convention de tags Consul pour le routage Traefik."""

import pytest

from commun.registre import tags_traefik


def test_une_ressource_donne_une_regle_path_prefix() -> None:
    tags = tags_traefik("billets", "places")

    assert tags == [
        "traefik.enable=true",
        "traefik.http.routers.billets.rule=PathPrefix(`/api/v1/places`)",
        "traefik.http.routers.billets.entrypoints=web",
        "traefik.http.routers.billets.middlewares=standard@file",
    ]


def test_plusieurs_ressources_sont_combinees_en_ou() -> None:
    tags = tags_traefik("catalogue", "evenements", "lieux")

    assert (
        "traefik.http.routers.catalogue.rule="
        "PathPrefix(`/api/v1/evenements`) || PathPrefix(`/api/v1/lieux`)"
    ) in tags


def test_chaine_partenaires() -> None:
    tags = tags_traefik("partenaires", "partenaires", middlewares="partenaires@file")

    assert "traefik.http.routers.partenaires.middlewares=partenaires@file" in tags


def test_sans_ressource_le_service_n_est_pas_routable() -> None:
    with pytest.raises(ValueError):
        tags_traefik("billets")
