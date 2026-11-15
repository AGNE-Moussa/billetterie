// Bascule du thème : bouton « Thème sombre » avec aria-pressed, lit et change useTheme. L'icône
// (lune ou soleil) est décorative ; le nom accessible reste le texte du bouton.
import { useTheme } from "../theme/theme";
import styles from "./BasculeTheme.module.css";

export function BasculeTheme() {
  const { theme, basculer } = useTheme();
  const sombre = theme === "sombre";
  return (
    <button type="button" className={styles.bascule} aria-pressed={sombre} onClick={basculer}>
      <svg
        className={styles.icone}
        viewBox="0 0 24 24"
        width="18"
        height="18"
        aria-hidden="true"
        focusable="false"
      >
        {sombre ? (
          <path
            d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"
            fill="currentColor"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
        ) : (
          <g stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" fill="none">
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4" />
          </g>
        )}
      </svg>
      <span>Thème sombre</span>
    </button>
  );
}
