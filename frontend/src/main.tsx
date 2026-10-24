// Point d'entrée : thème posé sur <html> avant le premier rendu (pas de flash, pas de script
// inline), feuille du thème, fournisseurs de thème et de notifications, client TanStack Query,
// routeur du navigateur, fournisseur d'authentification, puis la table des routes. Dans
// l'iframe de la reconnexion silencieuse, seule la réponse de Keycloak est transmise à la
// fenêtre parente.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";

import "./theme/theme.css";

import { CHEMIN_RAPPEL_SILENCIEUX, creerUserManager } from "./auth/configurationOidc";
import { FournisseurAuthentification } from "./auth/FournisseurAuthentification";
import { FournisseurNotifications } from "./notifications/FournisseurNotifications";
import { RoutesApplication } from "./RoutesApplication";
import { FournisseurTheme } from "./theme/FournisseurTheme";
import { appliquerThemeInitial } from "./theme/preference";

function demarrerApplication() {
  const racine = document.getElementById("root");
  if (racine === null) {
    throw new Error("Élément #root absent de index.html");
  }
  // Avant createRoot : FournisseurTheme part de la même valeur (choix retenu, sinon système).
  appliquerThemeInitial();
  const clientRequetes = new QueryClient();
  createRoot(racine).render(
    <StrictMode>
      <FournisseurTheme>
        <FournisseurNotifications>
          <QueryClientProvider client={clientRequetes}>
            <BrowserRouter>
              <FournisseurAuthentification>
                <RoutesApplication />
              </FournisseurAuthentification>
            </BrowserRouter>
          </QueryClientProvider>
        </FournisseurNotifications>
      </FournisseurTheme>
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
