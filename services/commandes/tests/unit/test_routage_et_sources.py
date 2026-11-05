"""Préfixe Traefik, appels inter-services et migrations de commandes (E8, E9, E10 du plan
BIL-008 ; décision Q25, contrainte du ticket, rules/migrations.md)."""

import ast
import re
from pathlib import Path

import pytest

from commandes.principal import NOM_SERVICE, RESSOURCES
from commun.registre import VARIABLE_POINT_ENTREE, tags_sante_traefik, tags_traefik

SERVICE = Path(__file__).resolve().parents[2]
SOURCES = SERVICE / "src" / "commandes"
VERSIONS = SERVICE / "alembic" / "versions"
CONTRAINTES = {
    "pk_commandes",
    "uq_commandes_client_cle_idempotence",
    "ck_commandes_statut",
    "ck_commandes_montant_total",
    "pk_lignes_commande",
    "fk_lignes_commande_commande",
    "ck_lignes_commande_montant",
}
FABRIQUES = {"PrimaryKeyConstraint", "UniqueConstraint", "ForeignKeyConstraint", "CheckConstraint"}


def test_commandes_et_paiements_s_inscrivent_avec_leurs_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(VARIABLE_POINT_ENTREE, raising=False)

    tags = tags_traefik(NOM_SERVICE, *RESSOURCES)
    sante = tags_sante_traefik(NOM_SERVICE, RESSOURCES[0])

    assert RESSOURCES == ("orders",)
    assert "traefik.http.routers.commandes.rule=PathPrefix(`/api/v1/orders`)" in tags
    regles = [t for t in sante if t.startswith("traefik.http.routers.commandes-sante.rule=")]
    assert len(regles) == 1
    assert "Path(`/api/v1/orders/health`)" in regles[0]
    assert "traefik.http.middlewares.commandes-sante.replacepath.path=/health" in sante


def test_commandes_et_paiements_n_ouvrent_aucun_client_http_direct() -> None:
    fautifs = []
    for fichier in SOURCES.rglob("*.py"):
        texte = fichier.read_text(encoding="utf-8")
        if re.search(r"AsyncClient\(|^\s*(import|from)\s+requests\b", texte, re.MULTILINE):
            fautifs.append(fichier.relative_to(SERVICE).as_posix())
    clients = (SOURCES / "infra" / "clients.py").read_text(encoding="utf-8")

    assert fautifs == []
    assert "ClientService" in clients


def _affectation(arbre: ast.Module, nom: str) -> object:
    for noeud in arbre.body:
        if isinstance(noeud, ast.AnnAssign) and noeud.value is not None:
            cible, valeur = noeud.target, noeud.value
        elif isinstance(noeud, ast.Assign):
            cible, valeur = noeud.targets[0], noeud.value
        else:
            continue
        if isinstance(cible, ast.Name) and cible.id == nom:
            return ast.literal_eval(valeur)
    raise AssertionError(f"{nom} absent")


def test_les_migrations_suivent_les_regles() -> None:
    fichiers = sorted(VERSIONS.glob("[0-9][0-9][0-9][0-9]_*.py"))
    numeros = [f.name[:4] for f in fichiers]
    nommees: set[str] = set()

    assert numeros == [f"{n:04d}" for n in range(1, len(fichiers) + 1)], numeros
    assert len(fichiers) >= 3, numeros
    precedente: str | None = None
    for fichier in fichiers:
        arbre = ast.parse(fichier.read_text(encoding="utf-8"))
        fonctions = {n.name for n in arbre.body if isinstance(n, ast.FunctionDef)}
        assert {"upgrade", "downgrade"} <= fonctions, fichier.name
        assert _affectation(arbre, "revision") == fichier.name[:4], fichier.name
        assert _affectation(arbre, "down_revision") == precedente, fichier.name
        precedente = fichier.name[:4]
        for appel in ast.walk(arbre):
            if not isinstance(appel, ast.Call):
                continue
            fonction = appel.func
            nom = fonction.attr if isinstance(fonction, ast.Attribute) else ""
            if nom in FABRIQUES:
                noms = [k.value for k in appel.keywords if k.arg == "name"]
                assert noms, f"{fichier.name} : {nom} sans nom explicite"
                nommees.add(ast.literal_eval(noms[0]))

    assert nommees >= CONTRAINTES, CONTRAINTES - nommees
