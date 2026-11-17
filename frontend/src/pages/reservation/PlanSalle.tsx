// Plan de salle (E03, BIL-020) : grille ARIA, un rang par ligne, une place par cellule. Trois
// états à l'écran (Q5 de docs/front/ecrans.md) : libre, indisponible (verrouillée ou vendue,
// `disponible: false`), sélectionnée. Navigation au clavier (CA2) : une seule place dans l'ordre
// de tabulation (tabindex mobile) ; flèches pour se déplacer, Début et Fin dans un rang,
// Espace ou Entrée pour sélectionner (bouton natif).
import { useRef, useState, type KeyboardEvent } from "react";

import type { Place } from "../../api/genere/billets";
import type { Categorie } from "../../api/genere/catalogue";
import { formaterEuros } from "../../format";
import { libellePlace, rangsDuPlan } from "./places";
import styles from "./PlanSalle.module.css";

export interface ProprietesPlanSalle {
  places: readonly Place[];
  categories: ReadonlyMap<string, Categorie>;
  /** Rang d'affichage de chaque catégorie (couleur de la légende). */
  indicesCategories: ReadonlyMap<string, number>;
  selection: readonly string[];
  /** Aucune sélection possible (séance annulée) : plan consultable seulement. */
  lectureSeule: boolean;
  surBasculer: (place: Place) => void;
}

interface Position {
  ligne: number;
  colonne: number;
}

function etatPlace(place: Place, selectionnee: boolean): string {
  if (selectionnee) return "sélectionnée";
  return place.disponible ? "libre" : "indisponible";
}

function Pastille({ etat, indice = 0 }: { etat: string; indice?: number }) {
  return (
    <span
      aria-hidden="true"
      className={`${styles.place ?? ""} ${styles.pastille ?? ""}`}
      data-etat={etat}
      data-categorie={String(indice % 6)}
    />
  );
}

export interface ProprietesLegende {
  categories: readonly Categorie[];
  indicesCategories: ReadonlyMap<string, number>;
}

/** Légende : les trois états, puis chaque catégorie avec son prix. */
export function LegendePlan({ categories, indicesCategories }: ProprietesLegende) {
  return (
    <>
      <ul className={styles.legende} aria-label="États des places">
        <li>
          <Pastille etat="libre" /> Libre
        </li>
        <li>
          <Pastille etat="indisponible" /> Indisponible
        </li>
        <li>
          <Pastille etat="selectionnee" /> Sélectionnée
        </li>
      </ul>
      <ul className={styles.legende} aria-label="Catégories et prix">
        {categories.map((categorie) => (
          <li key={categorie.id}>
            <Pastille etat="libre" indice={indicesCategories.get(categorie.id) ?? 0} />
            {categorie.nom} : {formaterEuros(categorie.prix)}
          </li>
        ))}
      </ul>
    </>
  );
}

export function PlanSalle({
  places,
  categories,
  indicesCategories,
  selection,
  lectureSeule,
  surBasculer,
}: ProprietesPlanSalle) {
  const rangs = rangsDuPlan(places);
  const boutons = useRef(new Map<string, HTMLButtonElement>());
  const [active, setActive] = useState<Position>({ ligne: 0, colonne: 0 });

  // Position active ramenée dans la grille (le plan peut changer au rafraîchissement).
  const ligneActive = Math.min(active.ligne, Math.max(rangs.length - 1, 0));
  const colonneActive = Math.min(
    active.colonne,
    Math.max((rangs[ligneActive]?.places.length ?? 1) - 1, 0),
  );

  const deplacer = (cible: Position) => {
    const rang = rangs[cible.ligne];
    if (rang === undefined) return;
    const colonne = Math.min(Math.max(cible.colonne, 0), rang.places.length - 1);
    const place = rang.places[colonne];
    if (place === undefined) return;
    setActive({ ligne: cible.ligne, colonne });
    boutons.current.get(place.id)?.focus();
  };

  const surTouche = (evenement: KeyboardEvent<HTMLButtonElement>, position: Position) => {
    const derniere = (rangs[position.ligne]?.places.length ?? 1) - 1;
    const cibles: Record<string, Position | undefined> = {
      ArrowLeft: { ligne: position.ligne, colonne: position.colonne - 1 },
      ArrowRight: { ligne: position.ligne, colonne: position.colonne + 1 },
      ArrowUp:
        position.ligne > 0 ? { ligne: position.ligne - 1, colonne: position.colonne } : undefined,
      ArrowDown:
        position.ligne < rangs.length - 1
          ? { ligne: position.ligne + 1, colonne: position.colonne }
          : undefined,
      Home: { ligne: position.ligne, colonne: 0 },
      End: { ligne: position.ligne, colonne: derniere },
    };
    if (!(evenement.key in cibles)) return;
    evenement.preventDefault();
    const cible = cibles[evenement.key];
    if (cible !== undefined) deplacer(cible);
  };

  return (
    <div className={styles.conteneur}>
      <p className={styles.scene} aria-hidden="true">
        Scène
      </p>
      <div
        role="grid"
        aria-label="Plan de salle : flèches pour se déplacer, Espace ou Entrée pour choisir une place"
        aria-readonly={lectureSeule ? true : undefined}
        className={styles.grille}
      >
        {rangs.map((rang, ligne) => (
          <div role="row" key={rang.rang} className={styles.rang}>
            <span role="rowheader" className={styles.nomRang}>
              {rang.rang}
            </span>
            {rang.places.map((place, colonne) => {
              const selectionnee = selection.includes(place.id);
              const categorie = categories.get(place.categorie_id);
              const indice = indicesCategories.get(place.categorie_id) ?? 0;
              const tarif =
                categorie !== undefined
                  ? `, catégorie ${categorie.nom}, ${formaterEuros(categorie.prix)}`
                  : "";
              const inactive = lectureSeule || (!place.disponible && !selectionnee);
              const estActive = ligne === ligneActive && colonne === colonneActive;
              return (
                <span role="gridcell" key={place.id} className={styles.cellule}>
                  <button
                    type="button"
                    ref={(element) => {
                      if (element === null) boutons.current.delete(place.id);
                      else boutons.current.set(place.id, element);
                    }}
                    tabIndex={estActive ? 0 : -1}
                    className={styles.place}
                    data-etat={
                      selectionnee ? "selectionnee" : place.disponible ? "libre" : "indisponible"
                    }
                    data-categorie={String(indice % 6)}
                    aria-label={`${libellePlace(place)}${tarif}, ${etatPlace(place, selectionnee)}`}
                    aria-pressed={selectionnee}
                    aria-disabled={inactive ? true : undefined}
                    onFocus={() => setActive({ ligne, colonne })}
                    onKeyDown={(evenement) => surTouche(evenement, { ligne, colonne })}
                    onClick={() => {
                      if (!inactive) surBasculer(place);
                    }}
                  >
                    <span aria-hidden="true">{place.numero}</span>
                  </button>
                </span>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
