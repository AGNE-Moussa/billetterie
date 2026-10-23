"""Réponse paginée commune à tous les services : `{elements, page, size, total}`.

Pagination à partir de 1 (`?page=&size=`). Chaque service sous-classe `Page[T]` pour donner au
schéma OpenAPI le nom de son contrat (ex. `class EchoPage(Page[EchoReponse])`).

Les bornes sont communes ; une route les reprend dans ses paramètres :
`page: Annotated[int, Query(ge=PAGE_MINIMALE)] = PAGE_PAR_DEFAUT`,
`size: Annotated[int, Query(ge=TAILLE_MINIMALE, le=TAILLE_MAXIMALE)] = TAILLE_PAR_DEFAUT`.
"""

from typing import Final

from pydantic import BaseModel

PAGE_MINIMALE: Final = 1
PAGE_PAR_DEFAUT: Final = 1
TAILLE_MINIMALE: Final = 1
TAILLE_PAR_DEFAUT: Final = 20
TAILLE_MAXIMALE: Final = 100


class Page[T](BaseModel):
    elements: list[T]
    page: int
    size: int
    total: int
