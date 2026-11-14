// Table des routes, sans routeur : main.tsx l'enveloppe dans BrowserRouter, les tests dans
// MemoryRouter. La mise en page commune (en-tête, navigation, pied de page) entoure toutes les
// pages, rendues dans son unique <main>. Plan complet : docs/front/routes.md.
import { Outlet, Route, Routes } from "react-router";

import { CHEMIN_RAPPEL } from "./auth/configurationOidc";
import { GardeRoles } from "./auth/GardeRoles";
import { MiseEnPage } from "./composants/MiseEnPage";
import { PageCatalogue } from "./pages/catalogue/PageCatalogue";
import { PageEvenement } from "./pages/catalogue/PageEvenement";
import { PageBillet } from "./pages/client/PageBillet";
import { PageBillets } from "./pages/client/PageBillets";
import { PageCommande } from "./pages/client/PageCommande";
import { PageCommandes } from "./pages/client/PageCommandes";
import { PageIntrouvable } from "./pages/PageIntrouvable";
import { PageRappelConnexion } from "./pages/PageRappelConnexion";
import { PagePaiement } from "./pages/reservation/PagePaiement";
import { PagePlanSalle } from "./pages/reservation/PagePlanSalle";

/** Routes réservées aux clients : une seule garde `customer` pour toutes (routes.md). */
function RoutesClient() {
  return (
    <GardeRoles roles={["customer"]}>
      <Outlet />
    </GardeRoles>
  );
}

export function RoutesApplication() {
  return (
    <MiseEnPage>
      <Routes>
        {/* R1 : le catalogue (E01) est la page d'accueil. */}
        <Route path="/" element={<PageCatalogue />} />
        <Route path="/evenements/:evenementId" element={<PageEvenement />} />
        {/* E03 public : seul « Réserver » demande la connexion. */}
        <Route path="/seances/:seanceId" element={<PagePlanSalle />} />
        <Route element={<RoutesClient />}>
          <Route path="/commandes" element={<PageCommandes />} />
          <Route path="/commandes/:commandeId" element={<PageCommande />} />
          <Route path="/commandes/:commandeId/paiement" element={<PagePaiement />} />
          <Route path="/billets" element={<PageBillets />} />
          <Route path="/billets/:billetId" element={<PageBillet />} />
        </Route>
        <Route path={CHEMIN_RAPPEL} element={<PageRappelConnexion />} />
        <Route path="*" element={<PageIntrouvable />} />
      </Routes>
    </MiseEnPage>
  );
}
