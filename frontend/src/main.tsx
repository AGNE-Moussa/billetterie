// Point d'entrée : client TanStack Query, routeur du navigateur, puis la table des routes.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";

import { RoutesApplication } from "./RoutesApplication";

const clientRequetes = new QueryClient();

const racine = document.getElementById("root");
if (racine === null) {
  throw new Error("Élément #root absent de index.html");
}

createRoot(racine).render(
  <StrictMode>
    <QueryClientProvider client={clientRequetes}>
      <BrowserRouter>
        <RoutesApplication />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
