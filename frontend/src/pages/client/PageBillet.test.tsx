// Cas composant de BIL-021 (E08, CA2) : un billet émis s'affiche avec son QR code, nommé par sa
// place ; un billet annulé n'a pas de QR code et l'annonce. API simulée par MSW ; QR synthétique.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";

import type { Billet } from "../../api/genere/billets";
import type { Evenement, Lieu, Seance } from "../../api/genere/catalogue";
import { serveurMsw } from "../../mocks/serveur";
import { PageBillet } from "./PageBillet";

const SEANCE: Seance = {
  id: "5e0a0000-0000-4000-8000-000000000001",
  evenement_id: "e0e00000-0000-4000-8000-000000000001",
  lieu_id: "11e00000-0000-4000-8000-000000000001",
  debut: "2026-12-12T20:00:00+01:00",
  annulee: false,
  categories: [],
};

function billet(statut: Billet["statut"]): Billet {
  return {
    id: "b1e70000-0000-4000-8000-000000000001",
    commande_id: "c0de0000-0000-4000-8000-000000000001",
    seance_id: SEANCE.id,
    place_id: "b1000000-0000-4000-8000-000000000000",
    rang: "B",
    numero: 12,
    statut,
    qr_code: "qr-signe-de-test",
    emis_le: "2026-11-12T18:05:00+01:00",
  };
}

function rendreBillet(donnees: Billet) {
  serveurMsw.use(
    http.get("*/api/v1/tickets/:billetId", () => HttpResponse.json<Billet>(donnees)),
    http.get("*/api/v1/shows/:seanceId", () => HttpResponse.json<Seance>(SEANCE)),
    http.get("*/api/v1/events/:evenementId", () =>
      HttpResponse.json<Evenement>({
        id: SEANCE.evenement_id,
        nom: "Concert de test",
        description: "Description synthétique.",
        cree_le: "2026-10-01T10:00:00+02:00",
      }),
    ),
    http.get("*/api/v1/venues/:lieuId", () =>
      HttpResponse.json<Lieu>({
        id: SEANCE.lieu_id,
        nom: "Salle de test",
        adresse: "1 rue de l'Exemple",
        ville: "Lyon",
        cree_le: "2026-10-01T10:00:00+02:00",
      }),
    ),
  );
  const clientRequetes = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={clientRequetes}>
      <MemoryRouter initialEntries={[`/billets/${donnees.id}`]}>
        <Routes>
          <Route path="/billets/:billetId" element={<PageBillet />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("test_un_billet_emis_s_affiche_avec_son_qr_code_nomme_par_sa_place", async () => {
  rendreBillet(billet("EMIS"));

  const qr = await screen.findByRole("img", { name: "QR code du billet rang b, place 12" });
  expect(qr.querySelector("path")?.getAttribute("d")).not.toBe("");
  expect(screen.getByText("Rang B, place 12")).toBeInTheDocument();
  expect(
    await screen.findByRole("heading", { level: 1, name: "Concert de test" }),
  ).toBeInTheDocument();
});

it("test_un_billet_annule_n_a_pas_de_qr_code_et_l_annonce", async () => {
  rendreBillet(billet("ANNULE"));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Billet annulé : séance annulée et commande remboursée.",
  );
  expect(screen.queryByRole("img", { name: /^QR code/ })).not.toBeInTheDocument();
});
