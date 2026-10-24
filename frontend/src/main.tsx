// Point d'entrée : client TanStack Query, routeur du navigateur, fournisseur
// d'authentification, puis la table des routes. Dans l'iframe de la reconnexion silencieuse,
// seule la réponse de Keycloak est transmise à la fenêtre parente.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";

import { CHEMIN_RAPPEL_SILENCIEUX, creerUserManager } from "./auth/configurationOidc";
import { FournisseurAuthentification } from "./auth/FournisseurAuthentification";
import { RoutesApplication } from "./RoutesApplication";

function demarrerApplication() {
  const racine = document.getElementById("root");
  if (racine === null) {
    throw new Error("Élément #root absent de index.html");
  }
  const clientRequetes = new QueryClient();
  createRoot(racine).render(
    <StrictMode>
      <QueryClientProvider client={clientRequetes}>
        <BrowserRouter>
          <FournisseurAuthentification>
            <RoutesApplication />
          </FournisseurAuthentification>
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}

if (window.location.pathname === CHEMIN_RAPPEL_SILENCIEUX) {
  // La fenêtre parente attend cette réponse ; une erreur la laisse expirer (non connecté).
  creerUserManager()
    .signinSilentCallback()
    .catch(() => {});
} else {
  demarrerApplication();
}
