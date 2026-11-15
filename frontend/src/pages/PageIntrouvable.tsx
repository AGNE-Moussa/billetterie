// Route inconnue : Nginx renvoie index.html (repli SPA), React Router affiche cette page, rendue
// dans le <main> de la mise en page.
import { Link } from "react-router";

import { IllustrationEtat } from "./IllustrationEtat";
import styles from "./PageEtat.module.css";

export function PageIntrouvable() {
  return (
    <div className={styles.etat}>
      <IllustrationEtat />
      <h1>Page introuvable</h1>
      <p>Cette page a quitté la scène, ou elle n'y est jamais montée.</p>
      <p>
        <Link to="/" className={styles.lien}>
          Retour à l'accueil
        </Link>
      </p>
    </div>
  );
}
