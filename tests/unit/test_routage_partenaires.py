"""Routage des revendeurs par Traefik (plan BIL-012, CA3, décisions Q1, Q2, H1).

Catalogue, Billets et Commandes annoncent, en plus de leur routeur standard, un routeur sur
l'hôte partenaires (`HOTE_PARTENAIRES`), mêmes chemins, chaîne `partenaires@file`. La chaîne
`partenaires` de `infra/traefik/dynamique.yml` vérifie le jeton par sa propre adresse, puis
applique le quota par jeton.
"""

import re
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

import billets.principal
import catalogue.principal
import commandes.principal
import notifications.principal
import paiements.principal
from commun.registre import VARIABLE_HOTE_PARTENAIRES, VARIABLE_POINT_ENTREE, tags_traefik

RACINE = Path(__file__).resolve().parents[2]
DYNAMIQUE = RACINE / "infra" / "traefik" / "dynamique.yml"
HOTE = "partenaires.localhost"
OUVERTS = [catalogue.principal, billets.principal, commandes.principal]
FERMES = [paiements.principal, notifications.principal]
TAG_ROUTEUR = re.compile(r"^traefik\.http\.routers\.([^.]+)\.([^=]+)=(.*)$")
ENTETES_IDENTITE = ["X-User-Id", "X-User-Roles", "X-Client-Id"]


@pytest.fixture(autouse=True)
def environnement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VARIABLE_HOTE_PARTENAIRES, HOTE)
    monkeypatch.delenv(VARIABLE_POINT_ENTREE, raising=False)


def _routeurs(tags: list[str]) -> dict[str, dict[str, str]]:
    routeurs: dict[str, dict[str, str]] = {}
    for tag in tags:
        trouve = TAG_ROUTEUR.match(tag)
        if trouve:
            nom, cle, valeur = trouve.groups()
            routeurs.setdefault(nom, {})[cle] = valeur
    return routeurs


def _tags(module: ModuleType) -> list[str]:
    fonction: Callable[[], list[str]] = module.tags_consul
    return fonction()


def _id(module: ModuleType) -> str:
    return str(module.NOM_SERVICE)


@pytest.mark.parametrize("module", OUVERTS, ids=_id)
def test_chaque_service_ouvert_aux_revendeurs_annonce_un_routeur_sur_l_hote_partenaires(
    module: ModuleType,
) -> None:
    routeurs = _routeurs(_tags(module))

    partenaires = [r for r in routeurs.values() if r.get("middlewares") == "partenaires@file"]
    assert len(partenaires) == 1, routeurs
    [routeur] = partenaires
    regle = routeur["rule"]
    assert f"Host(`{HOTE}`)" in regle
    for ressource in module.RESSOURCES:
        assert f"PathPrefix(`/api/v1/{ressource}`)" in regle
    assert routeur["entrypoints"] == "web"


@pytest.mark.parametrize("module", OUVERTS, ids=_id)
def test_le_routeur_standard_de_chaque_service_reste_sur_la_chaine_standard(
    module: ModuleType,
) -> None:
    tags = _tags(module)

    for tag in tags_traefik(module.NOM_SERVICE, *module.RESSOURCES):
        assert tag in tags
    assert _routeurs(tags)[module.NOM_SERVICE]["middlewares"] == "standard@file"


@pytest.mark.parametrize("module", FERMES, ids=_id)
def test_paiements_et_notifications_n_annoncent_aucun_routeur_partenaires(
    module: ModuleType,
) -> None:
    tags = _tags(module)

    assert not [t for t in tags if "partenaires@file" in t]
    assert not [t for t in tags if HOTE in t]


def _dynamique() -> dict[str, Any]:
    """`dynamique.yml` sans ses lignes de gabarit Go (liste des origines CORS)."""
    lignes = [
        ligne for ligne in DYNAMIQUE.read_text(encoding="utf-8").splitlines() if "{{" not in ligne
    ]
    contenu: dict[str, Any] = yaml.safe_load("\n".join(lignes))
    return contenu["http"]["middlewares"]


def _verification_de(middlewares: dict[str, Any], chaine: str) -> str:
    """Nom de l'unique middleware forwardAuth de la chaîne."""
    noms = [
        nom
        for nom in middlewares[chaine]["chain"]["middlewares"]
        if "forwardAuth" in middlewares[nom]
    ]
    assert len(noms) == 1, (chaine, noms)
    return noms[0]


def test_la_chaine_partenaires_limite_a_cinq_par_seconde_rafale_dix_par_jeton_valide() -> None:
    middlewares = _dynamique()

    limite = middlewares["limite-partenaires"]["rateLimit"]
    assert limite["average"] == 5
    assert limite["burst"] == 10
    assert limite["period"] == "1s"
    assert limite["sourceCriterion"] == {"requestHeaderName": "Authorization"}
    chaine = middlewares["partenaires"]["chain"]["middlewares"]
    verification = _verification_de(middlewares, "partenaires")
    assert chaine.index(verification) < chaine.index("limite-partenaires")


def test_chaque_chaine_appelle_sa_propre_verification_de_jeton() -> None:
    middlewares = _dynamique()

    standard = _verification_de(middlewares, "standard")
    partenaires = _verification_de(middlewares, "partenaires")

    assert standard != partenaires
    adresse_standard = middlewares[standard]["forwardAuth"]["address"]
    adresse_partenaires = middlewares[partenaires]["forwardAuth"]["address"]
    assert adresse_standard.endswith("/verifier")
    assert adresse_partenaires.endswith("/verifier/partenaires")
    for nom in (standard, partenaires):
        assert middlewares[nom]["forwardAuth"]["authResponseHeaders"] == ENTETES_IDENTITE
