// État commun « vide » : petite illustration décorative (fauteuils vides devant la scène),
// message et action facultative fournis par l'écran.
import type { ReactNode } from "react";

import styles from "./Vide.module.css";

export interface ProprietesVide {
  message: string;
  action?: ReactNode;
}

function Illustration() {
  return (
    <svg
      className={styles.illustration}
      viewBox="0 0 120 72"
      width="120"
      height="72"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M10 14 Q60 -2 110 14 L110 20 Q60 6 10 20 Z" fill="currentColor" opacity="0.35" />
      {[0, 1, 2, 3, 4].map((indice) => (
        <g key={indice} transform={`translate(${String(14 + indice * 20)} 34)`}>
          <rect width="16" height="14" rx="5" fill="currentColor" opacity="0.55" />
          <rect y="12" width="16" height="6" rx="2" fill="currentColor" opacity="0.8" />
        </g>
      ))}
      {[0, 1, 2, 3].map((indice) => (
        <g key={indice} transform={`translate(${String(24 + indice * 20)} 54)`}>
          <rect width="16" height="12" rx="5" fill="currentColor" opacity="0.4" />
          <rect y="10" width="16" height="6" rx="2" fill="currentColor" opacity="0.65" />
        </g>
      ))}
    </svg>
  );
}

export function Vide({ message, action }: ProprietesVide) {
  return (
    <div className={styles.vide}>
      <Illustration />
      <p className={styles.message}>{message}</p>
      {action !== undefined ? <div className={styles.action}>{action}</div> : null}
    </div>
  );
}
