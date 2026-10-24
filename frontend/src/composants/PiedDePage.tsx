// Pied de page minimal (contentinfo) : « Billetterie », sans lien tant qu'aucune page légale
// n'existe.
import styles from "./PiedDePage.module.css";

export function PiedDePage() {
  return (
    <footer className={styles.pied}>
      <p className={styles.texte}>Billetterie</p>
    </footer>
  );
}
