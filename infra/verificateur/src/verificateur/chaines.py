"""Chaînes Traefik servies par le vérificateur et rôles qu'elles admettent (BIL-012).

Chaque chaîne de `infra/traefik/dynamique.yml` qui vérifie le jeton appelle sa propre adresse :
`standard@file` sur `/verifier`, `partenaires@file` sur `/verifier/partenaires`. Un jeton
`partner` est refusé sur la chaîne standard (décision Q2 : un revendeur ne contourne pas son
quota) ; un jeton sans `partner` est refusé sur la chaîne partenaires (question 2 du plan).
"""

from collections.abc import Collection
from enum import StrEnum

ROLE_PARTENAIRE = "partner"


class Chaine(StrEnum):
    STANDARD = "standard"
    PARTENAIRES = "partenaires"


def role_admis(chaine: Chaine, roles: Collection[str]) -> bool:
    """Vrai si un jeton portant `roles` peut passer par `chaine`."""
    revendeur = ROLE_PARTENAIRE in roles
    if chaine is Chaine.PARTENAIRES:
        return revendeur
    return not revendeur
