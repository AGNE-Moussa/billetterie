// Bascule du thème : bouton « Thème sombre » avec aria-pressed, lit et change useTheme.
import { useTheme } from "../theme/theme";
import styles from "./BasculeTheme.module.css";

export function BasculeTheme() {
  const { theme, basculer } = useTheme();
  return (
    <button
      type="button"
      className={styles.bascule}
      aria-pressed={theme === "sombre"}
      onClick={basculer}
    >
      Thème sombre
    </button>
  );
}
