// Table des routes, sans routeur : main.tsx l'enveloppe dans BrowserRouter, les tests dans
// MemoryRouter.
import { Route, Routes } from "react-router";

import { PageAccueil } from "./pages/PageAccueil";
import { PageIntrouvable } from "./pages/PageIntrouvable";

export function RoutesApplication() {
  return (
    <Routes>
      <Route path="/" element={<PageAccueil />} />
      <Route path="*" element={<PageIntrouvable />} />
    </Routes>
  );
}
