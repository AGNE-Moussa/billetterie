// Route inconnue : Nginx renvoie index.html (repli SPA), React Router affiche cette page.
import { Link } from "react-router";

export function PageIntrouvable() {
  return (
    <main>
      <h1>Page introuvable</h1>
      <p>
        <Link to="/">Retour à l'accueil</Link>
      </p>
    </main>
  );
}
