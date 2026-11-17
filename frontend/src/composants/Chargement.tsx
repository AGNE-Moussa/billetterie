// État commun « chargement » : role="status", « Chargement… » par défaut. `forme` ajoute des
// squelettes décoratifs (aria-hidden) qui annoncent la mise en page à venir : grille de cartes,
// lignes de liste, ou bloc ; le libellé reste le seul texte annoncé.
import styles from "./Chargement.module.css";

export type FormeChargement = "texte" | "cartes" | "lignes" | "bloc";

export interface ProprietesChargement {
  libelle?: string;
  forme?: FormeChargement;
  /** Nombre de cartes ou de lignes du squelette. */
  nombre?: number;
}

export function Chargement({
  libelle = "Chargement…",
  forme = "texte",
  nombre = 3,
}: ProprietesChargement) {
  return (
    <div className={styles.chargement}>
      <p role="status" className={styles.libelle}>
        <span className={styles.indicateur} aria-hidden="true" />
        {libelle}
      </p>
      {forme === "cartes" ? (
        <ul className={styles.cartes} aria-hidden="true">
          {Array.from({ length: nombre }, (_, indice) => (
            <li key={indice} className={styles.carte}>
              <span className={`${styles.squelette ?? ""} ${styles.affiche ?? ""}`} />
              <span className={`${styles.squelette ?? ""} ${styles.titre ?? ""}`} />
              <span className={`${styles.squelette ?? ""} ${styles.ligne ?? ""}`} />
              <span className={`${styles.squelette ?? ""} ${styles.ligneCourte ?? ""}`} />
            </li>
          ))}
        </ul>
      ) : null}
      {forme === "lignes" ? (
        <ul className={styles.lignes} aria-hidden="true">
          {Array.from({ length: nombre }, (_, indice) => (
            <li key={indice} className={`${styles.squelette ?? ""} ${styles.rangee ?? ""}`} />
          ))}
        </ul>
      ) : null}
      {forme === "bloc" ? (
        <span className={`${styles.squelette ?? ""} ${styles.bloc ?? ""}`} aria-hidden="true" />
      ) : null}
    </div>
  );
}
