"""Réponse paginée commune `Page[T]` : `{elements, page, size, total}`."""

from pydantic import BaseModel

from commun.pagination import Page


class ElementDeTest(BaseModel):
    nom: str


class PageDeTest(Page[ElementDeTest]):
    pass


def test_une_page_generique_serialise_elements_page_size_total() -> None:
    page = PageDeTest(
        elements=[ElementDeTest(nom="element-test-01"), ElementDeTest(nom="element-test-02")],
        page=1,
        size=20,
        total=2,
    )

    assert set(page.model_dump(mode="json")) == {"elements", "page", "size", "total"}
