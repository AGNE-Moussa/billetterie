"""Comparaison du schéma OpenAPI généré par FastAPI au contrat validé (openapi.yaml).

Le contrat est écrit d'abord ; le code doit s'y conformer. Chaque différence est décrite par
son chemin dans le schéma, pour être corrigée sans chercher.
"""

from typing import Any


def differences_contrat(contrat: Any, genere: Any, chemin: str = "") -> list[str]:
    """Liste les différences entre le contrat et le schéma généré ; vide s'ils concordent."""
    if isinstance(contrat, dict) and isinstance(genere, dict):
        differences: list[str] = []
        for cle in sorted(set(contrat) | set(genere), key=str):
            sous_chemin = f"{chemin}.{cle}" if chemin else str(cle)
            if cle not in genere:
                differences.append(f"{sous_chemin} : dans le contrat, absent du code")
            elif cle not in contrat:
                differences.append(f"{sous_chemin} : dans le code, absent du contrat")
            else:
                differences.extend(differences_contrat(contrat[cle], genere[cle], sous_chemin))
        return differences

    if isinstance(contrat, list) and isinstance(genere, list) and len(contrat) == len(genere):
        differences = []
        for indice, (attendu, obtenu) in enumerate(zip(contrat, genere, strict=True)):
            differences.extend(differences_contrat(attendu, obtenu, f"{chemin}[{indice}]"))
        return differences

    if contrat != genere:
        return [f"{chemin} : contrat {contrat!r}, code {genere!r}"]
    return []
