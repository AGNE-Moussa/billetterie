// Table des routes, sans routeur : main.tsx l'enveloppe dans BrowserRouter, les tests dans
// MemoryRouter. La mise en page commune (en-tête, navigation, pied de page) entoure toutes les
// pages, rendues dans son unique <main>. Plan complet : docs/front/routes.md.
import { Route, Routes } from "react-router";

import { CHEMIN_RAPPEL } from "./auth/configurationOidc";
import { MiseEnPage } from "./composants/MiseEnPage";
import { PageCatalogue } from "./pages/catalogue/PageCatalogue";
import { PageEvenement } from "./pages/catalogue/PageEvenement";
import { PageIntrouvable } from "./pages/PageIntrouvable";
import { PageRappelConnexion } from "./pages/PageRappelConnexion";

export function RoutesApplication() {
  return (
    <MiseEnPage>
      <Routes>
        {/* R1 : le catalogue (E01) est la page d'accueil. */}
        <Route path="/" element={<PageCatalogue />} />
        <Route path="/evenements/:evenementId" element={<PageEvenement />} />
        <Route path={CHEMIN_RAPPEL} element={<PageRappelConnexion />} />
        <Route path="*" element={<PageIntrouvable />} />
      </Routes>
    </MiseEnPage>
  );
}
