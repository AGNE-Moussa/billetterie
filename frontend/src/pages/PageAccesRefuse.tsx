// Page « Accès refusé » rendue par une garde quand l'utilisateur connecté n'a aucun des rôles
// listés : h1 et lien vers l'accueil.
import { Link } from "react-router";

export function PageAccesRefuse() {
  return (
    <main>
      <h1>Accès refusé</h1>
      <p>
        <Link to="/">Retour à l'accueil</Link>
      </p>
    </main>
  );
}
