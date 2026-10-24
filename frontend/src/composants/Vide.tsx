// État commun « vide » : message et action facultative fournis par l'écran.
import type { ReactNode } from "react";

import styles from "./Vide.module.css";

export interface ProprietesVide {
  message: string;
  action?: ReactNode;
}

export function Vide({ message, action }: ProprietesVide) {
  return (
    <div className={styles.vide}>
      <p className={styles.message}>{message}</p>
      {action !== undefined ? <div>{action}</div> : null}
    </div>
  );
}
