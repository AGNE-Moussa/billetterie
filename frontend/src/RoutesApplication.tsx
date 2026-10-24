// Table des routes, sans routeur : main.tsx l'enveloppe dans BrowserRouter, les tests dans
// MemoryRouter. L'en-tête commun précède toutes les pages.
import { Route, Routes } from "react-router";

import { CHEMIN_RAPPEL } from "./auth/configurationOidc";
import { EnTete } from "./composants/EnTete";
import { PageAccueil } from "./pages/PageAccueil";
import { PageIntrouvable } from "./pages/PageIntrouvable";
import { PageRappelConnexion } from "./pages/PageRappelConnexion";

export function RoutesApplication() {
  return (
    <>
      <EnTete />
      <Routes>
        <Route path="/" element={<PageAccueil />} />
        <Route path={CHEMIN_RAPPEL} element={<PageRappelConnexion />} />
        <Route path="*" element={<PageIntrouvable />} />
      </Routes>
    </>
  );
}
