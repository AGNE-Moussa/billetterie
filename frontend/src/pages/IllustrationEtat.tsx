// Illustration décorative des pages d'état (introuvable, accès refusé) : un billet déchiré sous
// un projecteur. Masquée des technologies d'assistance.
import { useId } from "react";

import styles from "./PageEtat.module.css";

export function IllustrationEtat() {
  const idDegrade = useId();
  const idFaisceau = useId();
  return (
    <svg
      className={styles.illustration}
      viewBox="0 0 240 160"
      width="240"
      height="160"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id={idDegrade} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#d4147f" />
          <stop offset="1" stopColor="#5b2ee0" />
        </linearGradient>
        <linearGradient id={idFaisceau} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#b99cff" stopOpacity="0.45" />
          <stop offset="1" stopColor="#b99cff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d="M120 0 L60 150 L180 150 Z" fill={`url(#${idFaisceau})`} />
      <g transform="rotate(-10 80 100)">
        <path
          d="M40 78h52l-6 10 6 10-6 10 6 10H40a4 4 0 0 1-4-4v-8a6 6 0 0 0 0-12v-8a4 4 0 0 1 4-4z"
          fill={`url(#${idDegrade})`}
        />
      </g>
      <g transform="rotate(12 160 100)">
        <path
          d="M140 78h52a4 4 0 0 1 4 4v8a6 6 0 0 0 0 12v8a4 4 0 0 1-4 4h-52l6-10-6-10 6-10z"
          fill={`url(#${idDegrade})`}
          opacity="0.85"
        />
      </g>
      <ellipse cx="120" cy="150" rx="80" ry="6" fill="currentColor" opacity="0.12" />
    </svg>
  );
}
