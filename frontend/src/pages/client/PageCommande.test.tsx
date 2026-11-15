// Cas composant de BIL-021 (E05) : message clair pour une commande expirée (aucun débit, places
// libérées) ou remboursée (séance annulée) ; commande d'un autre client rendue comme une page
// introuvable. API simulée par MSW ; données synthétiques.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";

import type { Billet, BilletPage, PlacePage } from "../../api/genere/billets";
import type { Evenement, Lieu, Probleme, Seance } from "../../api/genere/catalogue";
import type { Commande } from "../../api/genere/commandes";
import { serveurMsw } from "../../mocks/serveur";
import { PageCommande } from "./PageCommande";

const COMMANDE_ID = "c0de0000-0000-4000-8000-000000000001";
const SEANCE: Seance = {
  id: "5e0a0000-0000-4000-8000-000000000001",
  evenement_id: "e0e00000-0000-4000-8000-000000000001",
  lieu_id: "11e00000-0000-4000-8000-000000000001",
  debut: "2026-12-12T20:00:00+01:00",
  annulee: false,
  categories: [],
};
const PLACE_ID = "b1000000-0000-4000-8000-000000000000";

function commande(statut: Commande["statut"]): Commande {
  return {
    id: COMMANDE_ID,
    seance_id: SEANCE.id,
    lignes: [{ place_id: PLACE_ID, montant: 4500 }],
    statut,
    montant_total: 4500,
    cree_le: "2026-11-12T18:04:00+01:00",
    expire_le: "2026-11-12T18:14:00+01:00",
  };
}

const BILLET_ANNULE: Billet = {
  id: "b1e70000-0000-4000-8000-000000000001",
  commande_id: COMMANDE_ID,
  seance_id: SEANCE.id,
  place_id: PLACE_ID,
  rang: "B",
  numero: 1,
  statut: "ANNULE",
  qr_code: "qr-signe-de-test",
  emis_le: "2026-11-12T18:05:00+01:00",
};

function simulerApi(reponseCommande: () => Response) {
  serveurMsw.use(
    http.get("*/api/v1/orders/:commandeId", reponseCommande),
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
    http.get("*/api/v1/seats", () =>
      HttpResponse.json<PlacePage>({ elements: [], page: 1, size: 100, total: 0 }),
    ),
    http.get("*/api/v1/tickets", () =>
      HttpResponse.json<BilletPage>({ elements: [BILLET_ANNULE], page: 1, size: 100, total: 1 }),
    ),
  );
}

function rendreCommande() {
  const clientRequetes = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={clientRequetes}>
      <MemoryRouter initialEntries={[`/commandes/${COMMANDE_ID}`]}>
        <Routes>
          <Route path="/commandes/:commandeId" element={<PageCommande />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("test_une_commande_expiree_annonce_aucun_debit_et_renvoie_vers_la_seance", async () => {
  simulerApi(() => HttpResponse.json<Commande>(commande("EXPIREE")));
  rendreCommande();

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Commande expirée : aucun débit, vos places sont libérées.",
  );
  expect(screen.getByText("Expirée")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Retour à la séance" })).toHaveAttribute(
    "href",
    `/seances/${SEANCE.id}`,
  );
  expect(screen.queryByRole("link", { name: /^Payer/ })).not.toBeInTheDocument();
});

it("test_une_commande_remboursee_annonce_l_annulation_de_la_seance_et_des_billets", async () => {
  simulerApi(() => HttpResponse.json<Commande>(commande("REMBOURSEE")));
  rendreCommande();

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Séance annulée, commande remboursée.",
  );
  expect(screen.getByText("Remboursée")).toBeInTheDocument();
  expect(await screen.findByText("Annulé (séance annulée)")).toBeInTheDocument();
});

it("test_la_commande_d_un_autre_client_s_affiche_comme_une_page_introuvable", async () => {
  simulerApi(() =>
    HttpResponse.json<Probleme>(
      {
        type: "about:blank",
        title: "Commande introuvable",
        status: 404,
        detail: "Aucune commande de test.",
        code: "ORDER_NOT_FOUND",
      },
      { status: 404, headers: { "Content-Type": "application/problem+json" } },
    ),
  );
  rendreCommande();

  expect(
    await screen.findByRole("heading", { level: 1, name: "Page introuvable" }),
  ).toBeInTheDocument();
});
