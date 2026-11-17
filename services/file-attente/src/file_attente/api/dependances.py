"""Dépendances injectées dans les routes (équivalent de l'injection de Symfony).

Les tests remplacent `obtenir_stockage` par `dependency_overrides` (file en mémoire).
"""

from typing import Annotated

from fastapi import Depends, Request

from file_attente.config import Parametres
from file_attente.domaine.file import FileIndisponible, ReglesFile, StockageFile
from file_attente.infra.file_redis import FileRedis


def obtenir_parametres(requete: Request) -> Parametres:
    parametres: Parametres = requete.app.state.parametres
    return parametres


def obtenir_regles(parametres: Annotated[Parametres, Depends(obtenir_parametres)]) -> ReglesFile:
    return ReglesFile(
        seances_sous_file=parametres.seances_sous_file,
        taille_vague=parametres.taille_vague,
        intervalle_vagues=parametres.intervalle_vagues,
        cle_signature=parametres.admission_cle_signature.get_secret_value(),
    )


def obtenir_file(requete: Request) -> FileRedis:
    """File Redis créée au démarrage ; absente : 503 FILE_INDISPONIBLE."""
    file: FileRedis | None = getattr(requete.app.state, "file", None)
    if file is None:
        raise FileIndisponible()
    return file


def obtenir_stockage(file: Annotated[FileRedis, Depends(obtenir_file)]) -> StockageFile:
    return file


ReglesDep = Annotated[ReglesFile, Depends(obtenir_regles)]
FileDep = Annotated[FileRedis, Depends(obtenir_file)]
StockageDep = Annotated[StockageFile, Depends(obtenir_stockage)]
