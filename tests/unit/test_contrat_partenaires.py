"""Documentation publiée des revendeurs, `docs/contrats/partenaires.yaml` (plan BIL-012,
décisions « Contrat », Q4 à Q8).

Chaque opération est recopiée à l'identique de son service (Catalogue, Billets, Commandes),
avec en plus la réponse 429 du quota de la gateway ; aucun contrat de service ne déclare ce 429.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[2]
PARTENAIRES = RACINE / "docs" / "contrats" / "partenaires.yaml"
SERVICES_SOURCES = ("catalogue", "billets", "commandes")
CONTRATS_SERVICES = sorted((RACINE / "services").glob("*/openapi.yaml"))
METHODES = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
OPERATIONS_PARTENAIRES = {
    "listerEvenements",
    "lireEvenement",
    "listerSeances",
    "lireSeance",
    "lireSeanceParId",
    "listerLieux",
    "lireLieu",
    "listerPlaces",
    "creerCommande",
    "listerCommandes",
    "lireCommande",
    "payerCommande",
}
OPERATIONS_COMMANDES = {"creerCommande", "listerCommandes", "lireCommande", "payerCommande"}
REF_QUOTA = {"$ref": "#/components/responses/QuotaDepasse"}


def _charger(fichier: Path) -> dict[str, Any]:
    contenu: dict[str, Any] = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    return contenu


def _operations(contrat: dict[str, Any]) -> dict[str, tuple[str, str, dict[str, Any]]]:
    return {
        operation["operationId"]: (chemin, methode, operation)
        for chemin, item in contrat["paths"].items()
        for methode, operation in item.items()
        if methode in METHODES
    }


def _resoudre(valeur: Any, document: dict[str, Any], pile: tuple[str, ...] = ()) -> Any:
    """Remplace récursivement chaque `$ref` local par son contenu résolu."""
    if isinstance(valeur, dict):
        ref = valeur.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            if ref in pile:
                return {"$ref-cyclique": ref}
            cible: Any = document
            for partie in ref[2:].split("/"):
                cible = cible[partie]
            return _resoudre(cible, document, (*pile, ref))
        return {cle: _resoudre(v, document, pile) for cle, v in valeur.items()}
    if isinstance(valeur, list):
        return [_resoudre(v, document, pile) for v in valeur]
    return valeur


@pytest.fixture(scope="module")
def partenaires() -> dict[str, Any]:
    return _charger(PARTENAIRES)


def test_chaque_operation_de_partenaires_est_identique_a_celle_de_son_service_hors_429(
    partenaires: dict[str, Any],
) -> None:
    sources: dict[str, tuple[str, str, Any]] = {}
    for service in SERVICES_SOURCES:
        contrat = _charger(RACINE / "services" / service / "openapi.yaml")
        for nom, (chemin, methode, operation) in _operations(contrat).items():
            sources[nom] = (chemin, methode, _resoudre(operation, contrat))

    differentes = []
    for nom, (chemin, methode, operation) in _operations(partenaires).items():
        resolue = _resoudre(operation, partenaires)
        reponses = {code: r for code, r in resolue["responses"].items() if code != "429"}
        sans_quota = {**resolue, "responses": reponses}
        if sources.get(nom) != (chemin, methode, sans_quota):
            differentes.append(nom)

    assert differentes == []


def test_le_document_partenaires_regroupe_exactement_les_operations_ouvertes_aux_revendeurs(
    partenaires: dict[str, Any],
) -> None:
    assert set(_operations(partenaires)) == OPERATIONS_PARTENAIRES


def test_chaque_operation_de_partenaires_declare_le_429_du_quota(
    partenaires: dict[str, Any],
) -> None:
    for nom, (_chemin, _methode, operation) in _operations(partenaires).items():
        assert operation["responses"].get("429") == REF_QUOTA, nom
    quota = partenaires["components"]["responses"]["QuotaDepasse"]
    assert "content" not in quota


@pytest.mark.parametrize(
    "contrat", CONTRATS_SERVICES, ids=[c.parent.name for c in CONTRATS_SERVICES]
)
def test_aucun_contrat_de_service_ne_declare_de_reponse_429(contrat: Path) -> None:
    operations = _operations(_charger(contrat))

    avec_429 = sorted(nom for nom, (_c, _m, op) in operations.items() if "429" in op["responses"])

    assert avec_429 == []


def test_seules_les_operations_de_commandes_exigent_le_jeton_httpbearer(
    partenaires: dict[str, Any],
) -> None:
    for nom, (_chemin, _methode, operation) in _operations(partenaires).items():
        if nom in OPERATIONS_COMMANDES:
            assert operation.get("security") == [{"HTTPBearer": []}], nom
        else:
            assert "security" not in operation, nom
    schemas = partenaires["components"]["securitySchemes"]
    assert set(schemas) == {"HTTPBearer"}
    assert schemas["HTTPBearer"]["type"] == "http"
    assert schemas["HTTPBearer"]["scheme"] == "bearer"
    assert "client_credentials" in partenaires["info"]["description"]
