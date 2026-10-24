// Carte : <article> nommé par son titre (aria-labelledby), titre h2 par défaut, contenu et
// actions facultatifs ; jamais la carte entière cliquable.
import { useId, type ReactNode } from "react";

import styles from "./Carte.module.css";

export type NiveauTitre = 2 | 3 | 4 | 5 | 6;

export interface ProprietesCarte {
  titre: string;
  niveauTitre?: NiveauTitre;
  children?: ReactNode;
  actions?: ReactNode;
}

export function Carte({ titre, niveauTitre = 2, children, actions }: ProprietesCarte) {
  const idTitre = useId();
  const Titre = `h${String(niveauTitre)}` as "h2" | "h3" | "h4" | "h5" | "h6";
  return (
    <article className={styles.carte} aria-labelledby={idTitre}>
      <Titre id={idTitre} className={styles.titre}>
        {titre}
      </Titre>
      {children !== undefined ? <div className={styles.contenu}>{children}</div> : null}
      {actions !== undefined ? <div className={styles.actions}>{actions}</div> : null}
    </article>
  );
}
