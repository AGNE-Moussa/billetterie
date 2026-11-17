"""Règles des migrations de notifications (E5 du plan BIL-009, décision Q8, H6 ;
rules/migrations.md), sans base."""

import ast
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
# Contraintes du modèle (docs/modele-donnees.md, section Notifications), nommées explicitement.
CONTRAINTES = {
    "pk_destinataires_commande",
    "pk_envois",
    "uq_envois_evenement_commande",
    "fk_envois_commande",
}
FABRIQUES = {"PrimaryKeyConstraint", "UniqueConstraint", "ForeignKeyConstraint", "CheckConstraint"}


def _migrations() -> list[Path]:
    return sorted(VERSIONS.glob("[0-9][0-9][0-9][0-9]_*.py"))


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


def test_les_migrations_de_notifications_suivent_les_regles() -> None:
    fichiers = _migrations()
    numeros = [f.name[:4] for f in fichiers]
    nommees: set[str] = set()

    assert numeros == [f"{n:04d}" for n in range(1, len(fichiers) + 1)], numeros
    assert len(fichiers) >= 3, numeros
    assert (VERSIONS / "0001_initiale.py").is_file()
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
    # Tables de messagerie reprises de la migration type d'echo (rules/migrations.md).
    messagerie = (VERSIONS / "0002_creer_tables_messagerie.py").read_text(encoding="utf-8")
    assert "outbox" in messagerie
    assert "messages_traites" in messagerie
