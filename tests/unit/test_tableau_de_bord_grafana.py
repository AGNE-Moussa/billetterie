"""Tableau de bord Grafana : les services métier y apparaissent (BIL-001, E5)."""

import json
import re
from pathlib import Path
from typing import Any

import yaml

RACINE = Path(__file__).resolve().parents[2]
TABLEAU = RACINE / "infra" / "grafana" / "tableaux" / "billetterie.json"
SOURCES = RACINE / "infra" / "grafana" / "provisioning" / "datasources" / "sources.yml"
PANNEAUX_PAR_SERVICE = ("Débit", "Latence p95", "Erreurs 5xx")


def _tableau() -> dict[str, Any]:
    contenu: dict[str, Any] = json.loads(TABLEAU.read_text(encoding="utf-8"))
    return contenu


def _panneaux_par_service() -> list[dict[str, Any]]:
    panneaux = [
        panneau
        for panneau in _tableau()["panels"]
        if any(str(panneau.get("title", "")).startswith(t) for t in PANNEAUX_PAR_SERVICE)
    ]
    assert len(panneaux) == len(PANNEAUX_PAR_SERVICE), [p.get("title") for p in panneaux]
    return panneaux


def _requetes(panneau: dict[str, Any]) -> list[str]:
    return [str(cible.get("expr", "")) for cible in panneau.get("targets") or []]


def test_le_tableau_de_bord_ne_filtre_sur_aucun_service_particulier() -> None:
    for panneau in _panneaux_par_service():
        for requete in _requetes(panneau):
            assert re.search(r"by \(service\b", requete), requete
            assert not re.search(r'service\s*=~?\s*"(?!\$service")[^"]*"', requete), requete


def test_le_tableau_de_bord_propose_une_variable_service() -> None:
    variables = {v.get("name"): v for v in _tableau()["templating"]["list"]}

    assert "service" in variables, "variable de modèle `service` absente"
    variable = variables["service"]
    requete = variable.get("query")
    texte = requete.get("query") if isinstance(requete, dict) else requete
    assert texte == 'label_values(up{job="services"}, service)'
    assert variable.get("multi") is True
    assert variable.get("includeAll") is True
    for panneau in _panneaux_par_service():
        for expression in _requetes(panneau):
            assert 'service=~"$service"' in expression, expression


def _filtres_de_up(panneau: dict[str, Any]) -> list[set[str]]:
    """Filtres de chaque requête `up{...}` du panneau ; échoue si une requête a une autre forme."""
    requetes = _requetes(panneau)
    assert requetes, panneau.get("title")
    filtres: list[set[str]] = []
    for requete in requetes:
        selecteur = re.fullmatch(r"\s*up\s*\{(.*)\}\s*", requete)
        assert selecteur is not None, requete
        filtres.append({f.replace(" ", "") for f in selecteur.group(1).split(",")})
    return filtres


def _panneau(titre: str) -> dict[str, Any]:
    panneaux = [p for p in _tableau()["panels"] if p.get("title") == titre]
    assert len(panneaux) == 1, f"panneau « {titre} » absent ou en double"
    return panneaux[0]


def test_le_panneau_instances_des_services_suit_la_variable_service() -> None:
    for filtres in _filtres_de_up(_panneau("Instances des services")):
        assert filtres == {'job="services"', 'service=~"$service"'}, filtres


def test_le_panneau_infrastructure_montre_les_autres_cibles() -> None:
    for filtres in _filtres_de_up(_panneau("Infrastructure")):
        assert filtres == {'job!="services"'}, filtres


def test_l_ancien_panneau_instances_mesurees_est_remplace() -> None:
    titres = [p.get("title") for p in _tableau()["panels"]]

    assert "Instances mesurées" not in titres


def test_le_tableau_de_bord_reste_un_json_grafana_valide() -> None:
    tableau = _tableau()
    sources = yaml.safe_load(SOURCES.read_text(encoding="utf-8"))["datasources"]
    declarees = {(s["type"], s["uid"]) for s in sources}

    assert tableau["uid"] == "billetterie"
    identifiants = [panneau["id"] for panneau in tableau["panels"]]
    assert len(identifiants) == len(set(identifiants))
    for panneau in tableau["panels"]:
        for cible in panneau.get("targets") or []:
            assert cible.get("refId"), panneau["title"]
            source = cible.get("datasource") or panneau.get("datasource") or {}
            assert source.get("type") in ("prometheus", "tempo"), panneau["title"]
            assert (source.get("type"), source.get("uid")) in declarees, panneau["title"]
