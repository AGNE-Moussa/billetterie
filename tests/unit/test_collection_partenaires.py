"""Collection Postman du parcours d'un revendeur, `postman/partenaires.json` (plan BIL-012, CA2,
H6, question 1 du plan).

Lue en JSON, sans la jouer (le parcours est rejoué par Newman en smoke) : jeton Client
Credentials, puis listerEvenements, listerSeances, listerPlaces, creerCommande, lireCommande,
listerCommandes, chacun avec ses assertions Postman ; aucun secret dans le fichier.
"""

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[2]
COLLECTION = RACINE / "postman" / "partenaires.json"
PARTENAIRES = RACINE / "docs" / "contrats" / "partenaires.yaml"
METHODES = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
PARCOURS = [
    "listerEvenements",
    "listerSeances",
    "listerPlaces",
    "creerCommande",
    "lireCommande",
    "listerCommandes",
]
CHEMIN_JETON = "/protocol/openid-connect/token"
CARTES_DE_TEST = {"4242424242424242", "4000000000000002"}
VARIABLE = re.compile(r"^\{\{([^{}]+)\}\}$")


def _requetes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Requêtes de la collection dans l'ordre, dossiers aplatis."""
    trouvees: list[dict[str, Any]] = []
    for item in items:
        if "item" in item:
            trouvees += _requetes(item["item"])
        elif "request" in item:
            trouvees.append(item)
    return trouvees


@pytest.fixture(scope="module")
def requetes() -> list[dict[str, Any]]:
    collection: dict[str, Any] = json.loads(COLLECTION.read_text(encoding="utf-8"))
    return _requetes(collection.get("item", []))


def _url_brute(requete: dict[str, Any]) -> str:
    url = requete["request"]["url"]
    return str(url["raw"] if isinstance(url, dict) else url)


def _hote_et_chemin(requete: dict[str, Any]) -> tuple[str, str]:
    url = requete["request"]["url"]
    if isinstance(url, dict) and "path" in url:
        hote = ".".join(url.get("host", []))
        chemin = "/" + "/".join(str(p) for p in url["path"])
        return hote, chemin
    brute = _url_brute(requete)
    if "://" not in brute:
        brute = "http://" + brute
    morceaux = urlsplit(brute)
    return morceaux.netloc, morceaux.path


def _est_jeton(requete: dict[str, Any]) -> bool:
    return _hote_et_chemin(requete)[1].endswith(CHEMIN_JETON)


def _operations_partenaires() -> list[tuple[str, re.Pattern[str], str]]:
    contrat: dict[str, Any] = yaml.safe_load(PARTENAIRES.read_text(encoding="utf-8"))
    operations = []
    for chemin, item in contrat["paths"].items():
        for methode, operation in item.items():
            if methode in METHODES:
                motif = re.sub(r"\\\{[^/]+?\\\}", "[^/]+", re.escape(chemin))
                operations.append(
                    (methode.upper(), re.compile(f"^{motif}$"), operation["operationId"])
                )
    return operations


def _operation_de(requete: dict[str, Any]) -> str | None:
    methode = str(requete["request"]["method"]).upper()
    chemin = _hote_et_chemin(requete)[1]
    # Un segment {param} du contrat accepte une variable Postman ({{id}} ou :id) ; une requête
    # qui correspondrait à plusieurs opérations n'en vise aucune.
    candidates = [
        nom for m, motif, nom in _operations_partenaires() if m == methode and motif.match(chemin)
    ]
    return candidates[0] if len(candidates) == 1 else None


def _scripts_de_test(requete: dict[str, Any]) -> list[str]:
    return [
        "\n".join(e.get("script", {}).get("exec", []))
        for e in requete.get("event", [])
        if e.get("listen") == "test"
    ]


def _variable_du_jeton(requete: dict[str, Any]) -> str | None:
    """Variable Postman portée en `Authorization: Bearer {{...}}` (en-tête ou auth bearer)."""
    for entete in requete["request"].get("header", []):
        if str(entete.get("key", "")).lower() == "authorization":
            trouve = re.fullmatch(r"Bearer \{\{([^{}]+)\}\}", str(entete.get("value", "")))
            if trouve:
                return trouve.group(1)
    auth = requete["request"].get("auth") or {}
    if auth.get("type") == "bearer":
        for champ in auth.get("bearer", []):
            if champ.get("key") == "token":
                trouve = VARIABLE.fullmatch(str(champ.get("value", "")))
                if trouve:
                    return trouve.group(1)
    return None


def test_la_collection_partenaires_deroule_le_parcours_dans_l_ordre(
    requetes: list[dict[str, Any]],
) -> None:
    assert requetes, "collection vide"
    assert _est_jeton(requetes[0])
    appels = requetes[1:]

    assert [_operation_de(r) for r in appels] == PARCOURS
    for requete in requetes:
        scripts = _scripts_de_test(requete)
        assert any(s.strip() for s in scripts), requete.get("name")


def test_chaque_requete_de_la_collection_vise_une_operation_de_partenaires_yaml(
    requetes: list[dict[str, Any]],
) -> None:
    appels = [r for r in requetes if not _est_jeton(r)]
    assert appels, "aucun appel d'API dans la collection"

    hotes = set()
    for requete in appels:
        assert _operation_de(requete) is not None, _url_brute(requete)
        hote = _hote_et_chemin(requete)[0]
        assert VARIABLE.fullmatch(hote), hote
        hotes.add(hote)
    # Un seul hôte, celui des revendeurs, porté par une variable.
    assert len(hotes) == 1


def test_la_collection_obtient_son_jeton_par_client_credentials_seulement(
    requetes: list[dict[str, Any]],
) -> None:
    jetons = [r for r in requetes if _est_jeton(r)]
    assert len(jetons) == 1
    [jeton] = jetons
    corps = jeton["request"].get("body", {})
    assert corps.get("mode") == "urlencoded"
    champs = {c["key"]: c.get("value") for c in corps.get("urlencoded", [])}
    assert champs.get("grant_type") == "client_credentials"
    assert champs.get("client_id") == "revendeur-test"
    assert champs.get("client_secret") == "{{client_secret}}"
    assert "username" not in champs
    assert "password" not in champs

    variables = {_variable_du_jeton(r) for r in requetes if not _est_jeton(r)}
    assert len(variables) == 1
    [variable] = variables
    assert variable is not None
    # La variable est remplie par le script de la requête de jeton, depuis access_token.
    script = "\n".join(_scripts_de_test(jeton))
    assert "access_token" in script
    assert variable in script


def test_la_collection_partenaires_ne_contient_aucun_secret() -> None:
    brut = COLLECTION.read_text(encoding="utf-8")
    collection: dict[str, Any] = json.loads(brut)

    assert "{{client_secret}}" in brut
    variables = {v["key"]: v.get("value") for v in collection.get("variable", [])}
    assert variables.get("client_secret") == ""
    # Aucun jeton JWT écrit en dur.
    assert not re.search(r"eyJ[A-Za-z0-9_-]{10,}\.", brut)
    # Aucun numéro de carte autre que les cartes de test du contrat.
    assert set(re.findall(r"(?<!\d)\d{16}(?!\d)", brut)) <= CARTES_DE_TEST
