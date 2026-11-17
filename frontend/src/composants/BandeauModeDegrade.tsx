// Bandeau du mode dégradé : affiché au-dessus du contenu quand une lecture du catalogue a été
// servie depuis le cache de secours (`X-Cache-Stale: true`). Annoncé poliment (role="status").
import styles from "./BandeauModeDegrade.module.css";

export function BandeauModeDegrade() {
  return (
    <p role="status" className={styles.bandeau}>
      <strong>Données peut-être pas à jour.</strong> Le catalogue est momentanément servi depuis une
      copie de secours.
    </p>
  );
}
