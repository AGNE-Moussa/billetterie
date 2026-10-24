// Page « Accès refusé » rendue par une garde quand l'utilisateur connecté n'a aucun des rôles
// listés : h1 et lien vers l'accueil, dans le <main> de la mise en page.
import { Link } from "react-router";

export function PageAccesRefuse() {
  return (
    <>
      <h1>Accès refusé</h1>
      <p>
        <Link to="/">Retour à l'accueil</Link>
      </p>
    </>
  );
}
