// Tableau à pagination contrôlée : reçoit une page `{elements, page, size, total}` et demande
// la page voisine par `surChangerPage` ; l'écran fait la requête. Sans élément : état vide.
// Les boutons aux bornes ou pendant l'état occupé sont inactifs (aria-disabled, focus conservé).
import { useId, type ReactNode } from "react";

import { Bouton } from "./Bouton";
import styles from "./TableauPagine.module.css";
import { Vide } from "./Vide";

/** Page d'une collection (forme `commun.pagination.Page` des conventions, `page` ≥ 1). */
export interface Page<T> {
  elements: readonly T[];
  page: number;
  size: number;
  total: number;
}

export interface ColonneTableau<T> {
  entete: string;
  rendu: (element: T) => ReactNode;
}

export interface ProprietesTableauPagine<T> {
  /** Nom accessible du tableau. */
  libelle: string;
  colonnes: readonly ColonneTableau<T>[];
  page: Page<T>;
  /** Clé React stable d'une ligne. */
  cleLigne: (element: T) => string;
  surChangerPage: (numero: number) => void;
  /** Message de l'état vide, fourni par l'écran. */
  messageVide: string;
  /** Pose aria-busy et rend la pagination inactive. */
  occupe?: boolean;
}

/** Nombre de pages de la collection, au moins 1. */
function nombreDePages({ size, total }: Page<unknown>): number {
  return size > 0 ? Math.max(1, Math.ceil(total / size)) : 1;
}

export function TableauPagine<T>({
  libelle,
  colonnes,
  page,
  cleLigne,
  surChangerPage,
  messageVide,
  occupe = false,
}: ProprietesTableauPagine<T>) {
  const idLegende = useId();
  if (page.elements.length === 0) {
    return <Vide message={messageVide} />;
  }
  const pages = nombreDePages(page);

  return (
    <div className={styles.conteneur}>
      {/* Zone défilante focalisable et nommée : un tableau large défile au clavier (flèches).
          Exception voulue à la règle (décision validation 2) : c'est le motif recommandé pour
          une zone défilante, que tous les navigateurs ne rendent pas focalisable d'eux-mêmes. */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <div className={styles.defilement} role="region" aria-labelledby={idLegende} tabIndex={0}>
        <table className={styles.tableau} aria-busy={occupe ? true : undefined}>
          <caption id={idLegende} className={styles.legende}>
            {libelle}
          </caption>
          <thead>
            <tr>
              {colonnes.map((colonne, index) => (
                // Colonnes fixes pour un tableau donné : l'index est une clé stable et unique.
                <th key={index} scope="col">
                  {colonne.entete}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {page.elements.map((element) => (
              <tr key={cleLigne(element)}>
                {colonnes.map((colonne, index) => (
                  <td key={index}>{colonne.rendu(element)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <nav aria-label="Pagination" className={styles.pagination}>
        <Bouton
          variante="secondaire"
          inactif={occupe || page.page <= 1}
          surClic={() => surChangerPage(page.page - 1)}
        >
          Page précédente
        </Bouton>
        <p className={styles.position} aria-live="polite">
          {`Page ${String(page.page)} sur ${String(pages)}`}
        </p>
        <Bouton
          variante="secondaire"
          inactif={occupe || page.page >= pages}
          surClic={() => surChangerPage(page.page + 1)}
        >
          Page suivante
        </Bouton>
      </nav>
    </div>
  );
}
