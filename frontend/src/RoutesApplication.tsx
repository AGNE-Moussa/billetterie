// Table des routes, sans routeur : main.tsx l'enveloppe dans BrowserRouter, les tests dans
// MemoryRouter. La mise en page commune (en-tête, navigation, pied de page) entoure toutes les
// pages, rendues dans son unique <main>.
import { Route, Routes } from "react-router";

import { CHEMIN_RAPPEL } from "./auth/configurationOidc";
import { MiseEnPage } from "./composants/MiseEnPage";
import { PageAccueil } from "./pages/PageAccueil";
import { PageIntrouvable } from "./pages/PageIntrouvable";
import { PageRappelConnexion } from "./pages/PageRappelConnexion";

export function RoutesApplication() {
  return (
    <MiseEnPage>
      <Routes>
        <Route path="/" element={<PageAccueil />} />
        <Route path={CHEMIN_RAPPEL} element={<PageRappelConnexion />} />
        <Route path="*" element={<PageIntrouvable />} />
      </Routes>
    </MiseEnPage>
  );
}
