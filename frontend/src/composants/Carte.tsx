// Carte : <article> nommé par son titre (aria-labelledby), titre h2 par défaut, visuel décoratif,
// contenu et actions facultatifs ; jamais la carte entière cliquable.
import { useId, type ReactNode } from "react";

import styles from "./Carte.module.css";

export type NiveauTitre = 2 | 3 | 4 | 5 | 6;

export interface ProprietesCarte {
  titre: string;
  niveauTitre?: NiveauTitre;
  children?: ReactNode;
  actions?: ReactNode;
  /** Visuel affiché en tête de carte (affiche générée, bandeau) ; décoratif. */
  visuel?: ReactNode;
}

export function Carte({ titre, niveauTitre = 2, children, actions, visuel }: ProprietesCarte) {
  const idTitre = useId();
  const Titre = `h${String(niveauTitre)}` as "h2" | "h3" | "h4" | "h5" | "h6";
  return (
    <article
      className={`${styles.carte ?? ""} ${visuel !== undefined ? (styles.avecVisuel ?? "") : ""}`}
      aria-labelledby={idTitre}
    >
      {visuel !== undefined ? <div className={styles.visuel}>{visuel}</div> : null}
      <div className={styles.corps}>
        <Titre id={idTitre} className={styles.titre}>
          {titre}
        </Titre>
        {children !== undefined ? <div className={styles.contenu}>{children}</div> : null}
        {actions !== undefined ? <div className={styles.actions}>{actions}</div> : null}
      </div>
    </article>
  );
}
