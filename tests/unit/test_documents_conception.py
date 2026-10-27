"""Documents de conception (BIL-002) : contrats cibles, schémas d'événements, modèle de données."""

import json
import re
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate

from commun.evenements import Evenement

RACINE = Path(__file__).resolve().parents[2]
CONTRATS = sorted((RACINE / "docs" / "contrats").glob("*.yaml"))
SCHEMAS_EVENEMENTS = sorted((RACINE / "docs" / "evenements").glob("*.json"))
SERVICES_METIER = sorted(
    p.name for p in (RACINE / "services").iterdir() if p.is_dir() and p.name != "echo"
)


def _evenements_de_la_conception() -> set[str]:
    texte = (RACINE / "docs" / "conception.md").read_text(encoding="utf-8")
    return set(re.findall(r"^\| `(ticketing\.[a-z_.]+)` \|", texte, flags=re.MULTILINE))


def _schema(type_evenement: str) -> dict[str, Any]:
    chemin = RACINE / "docs" / "evenements" / f"{type_evenement}.json"
    schema: dict[str, Any] = json.loads(chemin.read_text(encoding="utf-8"))
    return schema


@pytest.mark.parametrize("contrat", CONTRATS, ids=[c.stem for c in CONTRATS])
def test_chaque_contrat_cible_est_un_openapi_valide(contrat: Path) -> None:
    validate(yaml.safe_load(contrat.read_text(encoding="utf-8")))


def test_chaque_service_metier_a_son_contrat_cible() -> None:
    assert sorted(c.stem for c in CONTRATS) == SERVICES_METIER


def test_chaque_evenement_de_la_conception_a_son_schema() -> None:
    assert {s.stem for s in SCHEMAS_EVENEMENTS} == _evenements_de_la_conception()


@pytest.mark.parametrize("chemin", SCHEMAS_EVENEMENTS, ids=[s.stem for s in SCHEMAS_EVENEMENTS])
def test_chaque_schema_d_evenement_est_valide_et_porte_son_type(chemin: Path) -> None:
    schema = json.loads(chemin.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["type"] == {"const": chemin.stem}


def _uuid() -> str:
    return str(uuid.uuid4())


EXEMPLES: dict[str, dict[str, Any]] = {
    "ticketing.show.scheduled": {
        "seance_id": _uuid(),
        "evenement_id": _uuid(),
        "evenement_nom": "Concert de test",
        "lieu_id": _uuid(),
        "lieu_nom": "Salle de test",
        "ville": "Villetest",
        "debut": "2030-01-01T20:00:00+00:00",
        "categories": [
            {
                "categorie_id": _uuid(),
                "nom": "Fosse",
                "prix": 4500,
                "rangs": [{"rang": "A", "nombre_places": 20}],
            }
        ],
    },
    "ticketing.show.cancelled": {"seance_id": _uuid(), "evenement_id": _uuid()},
    "ticketing.order.confirmed": {
        "commande_id": _uuid(),
        "client": "client-test",
        "email": "client.test@exemple.test",
        "seance_id": _uuid(),
        "lignes": [{"place_id": _uuid(), "montant": 4500}],
        "montant_total": 4500,
    },
    "ticketing.order.expired": {
        "commande_id": _uuid(),
        "seance_id": _uuid(),
        "place_ids": [_uuid()],
    },
    "ticketing.ticket.issued": {
        "billet_id": _uuid(),
        "commande_id": _uuid(),
        "seance_id": _uuid(),
        "place_id": _uuid(),
        "qr_code": "qr-test",
        "emis_le": "2030-01-01T19:00:00+00:00",
    },
    "ticketing.ticket.rejected": {
        "commande_id": _uuid(),
        "seance_id": _uuid(),
        "place_ids": [_uuid()],
        "motif": "PLACE_DEJA_VENDUE",
    },
    "ticketing.payment.refunded": {
        "paiement_id": _uuid(),
        "commande_id": _uuid(),
        "seance_id": _uuid(),
        "montant": 4500,
    },
}


def test_chaque_schema_d_evenement_a_son_exemple() -> None:
    assert set(EXEMPLES) == {s.stem for s in SCHEMAS_EVENEMENTS}


@pytest.mark.parametrize("type_evenement", sorted(EXEMPLES))
def test_l_enveloppe_commune_respecte_le_schema_de_chaque_evenement(type_evenement: str) -> None:
    evenement = Evenement.creer(type_evenement, EXEMPLES[type_evenement])
    validateur = Draft202012Validator(_schema(type_evenement), format_checker=FormatChecker())

    assert not list(validateur.iter_errors(evenement.model_dump(mode="json")))


def _tables_et_relations_par_service() -> dict[str, tuple[set[str], set[str]]]:
    """Par section du modèle : tables décrites, et tables citées par une relation Mermaid."""
    texte = (RACINE / "docs" / "modele-donnees.md").read_text(encoding="utf-8")
    resultat = {}
    for section in re.split(r"^## ", texte, flags=re.MULTILINE)[1:]:
        tables = set(re.findall(r"^  ([a-z_]+) \{$", section, flags=re.MULTILINE))
        relations = re.findall(r"^  ([a-z_]+) \S+--\S+ ([a-z_]+) :", section, flags=re.MULTILINE)
        resultat[section.splitlines()[0].lower()] = (
            tables,
            {t for paire in relations for t in paire},
        )
    return resultat


def test_le_modele_de_donnees_a_une_section_par_service_metier() -> None:
    assert sorted(_tables_et_relations_par_service()) == SERVICES_METIER


def test_aucune_relation_ne_traverse_deux_services() -> None:
    for service, (tables, tables_reliees) in _tables_et_relations_par_service().items():
        assert tables_reliees <= tables, f"{service} relie une table d'un autre service"
