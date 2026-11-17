// Page « Accès refusé » rendue par une garde quand l'utilisateur connecté n'a aucun des rôles
// listés : h1 et lien vers l'accueil, dans le <main> de la mise en page.
import { Link } from "react-router";

import { IllustrationEtat } from "./IllustrationEtat";
import styles from "./PageEtat.module.css";

export function PageAccesRefuse() {
  return (
    <div className={styles.etat}>
      <IllustrationEtat />
      <h1>Accès refusé</h1>
      <p>
        <Link to="/" className={styles.lien}>
          Retour à l'accueil
        </Link>
      </p>
    </div>
  );
}
