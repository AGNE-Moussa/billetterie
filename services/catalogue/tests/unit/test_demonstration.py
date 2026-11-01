"""Jeu de données de démonstration (E7, décision Q17 du plan BIL-004), sans base."""

import dataclasses
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from catalogue.demo import jeu_de_demonstration

MAINTENANT = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
COURRIEL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
# Motifs de secrets : jeton JWT, en-tête Bearer, clé privée, mot de passe.
SECRETS = re.compile(r"eyJ[\w-]{10,}|Bearer\s|PRIVATE KEY|mot de passe|password", re.IGNORECASE)


def _textes(valeur: Any) -> Iterator[str]:
    if isinstance(valeur, str):
        yield valeur
    elif dataclasses.is_dataclass(valeur) and not isinstance(valeur, type):
        for champ in dataclasses.fields(valeur):
            yield from _textes(getattr(valeur, champ.name))
    elif isinstance(valeur, list | tuple):
        for element in valeur:
            yield from _textes(element)


def test_le_jeu_de_demonstration_est_synthetique() -> None:
    jeu = jeu_de_demonstration(MAINTENANT)

    textes = list(_textes(jeu))
    domaines = {m.group(1) for t in textes for m in COURRIEL.finditer(t)}
    assert domaines <= {"exemple.test"}
    assert [t for t in textes if SECRETS.search(t)] == []

    assert jeu.lieux and jeu.evenements
    for lieu in jeu.lieux:
        assert 1 <= len(lieu.nom) <= 200
        assert 1 <= len(lieu.adresse) <= 300
        assert 1 <= len(lieu.ville) <= 100
    for evenement in jeu.evenements:
        assert 1 <= len(evenement.nom) <= 200
        assert len(evenement.description) <= 5000
        for seance in evenement.seances:
            assert seance.debut.utcoffset() is not None
            assert seance.debut > MAINTENANT
            assert 1 <= len(seance.categories) <= 20
            rangs: list[str] = []
            for categorie in seance.categories:
                assert 1 <= len(categorie.nom) <= 100
                assert isinstance(categorie.prix, int)
                assert not isinstance(categorie.prix, bool)
                assert categorie.prix > 0
                assert 1 <= len(categorie.rangs) <= 100
                for rang in categorie.rangs:
                    assert 1 <= len(rang.rang) <= 10
                    assert 1 <= rang.nombre_places <= 1000
                rangs += [rang.rang for rang in categorie.rangs]
            assert len(rangs) == len(set(rangs)), (evenement.nom, seance.debut, rangs)
