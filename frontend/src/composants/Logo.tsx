// Marque « Ovation » : billet stylisé (encoches latérales, pointillés de détachement, étoile)
// en SVG inline, suivi du nom. Décoratif pour les technologies d'assistance : le nom est lu en
// texte, l'image est masquée (aria-hidden). Jamais un lien : l'en-tête garde son ordre de
// tabulation (évitement, navigation, thème, connexion).
import { useId } from "react";

import styles from "./Logo.module.css";

export const NOM_MARQUE = "Ovation";

export function Logo() {
  const idDegrade = useId();
  return (
    <span className={styles.logo}>
      <svg
        className={styles.icone}
        viewBox="0 0 48 32"
        width="44"
        height="30"
        aria-hidden="true"
        focusable="false"
      >
        <defs>
          <linearGradient id={idDegrade} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#ff4fae" />
            <stop offset="0.55" stopColor="#a63be6" />
            <stop offset="1" stopColor="#5b2ee0" />
          </linearGradient>
        </defs>
        <g transform="rotate(-8 24 16)">
          <path
            d="M6 4h36a2 2 0 0 1 2 2v6a4 4 0 0 0 0 8v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-6a4 4 0 0 0 0-8V6a2 2 0 0 1 2-2z"
            fill={`url(#${idDegrade})`}
          />
          <path
            d="M33 7v18"
            stroke="#ffffff"
            strokeOpacity="0.7"
            strokeWidth="1.6"
            strokeDasharray="2 2.4"
            strokeLinecap="round"
          />
          <path
            d="M18.5 9.5l1.9 3.9 4.3.6-3.1 3 .7 4.3-3.8-2-3.8 2 .7-4.3-3.1-3 4.3-.6z"
            fill="#ffffff"
          />
        </g>
      </svg>
      <span className={styles.nom}>{NOM_MARQUE}</span>
    </span>
  );
}
