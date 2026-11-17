// Cas composant de BIL-022 (CA2, E11) : un 422 REQUETE_INVALIDE s'affiche sous le champ concerné
// (préfixe « body. » retiré), formulaire sans validation du navigateur ; succès : renvoi vers
// E12. API simulée par MSW ; données synthétiques.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";

import type { Evenement, EvenementCreation, Probleme } from "../../api/genere/catalogue";
import { serveurMsw } from "../../mocks/serveur";
import { PageNouvelEvenement } from "./PageNouvelEvenement";

const EVENEMENT_ID = "e0e00000-0000-4000-8000-000000000001";

function rendrePage() {
  const clientRequetes = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={clientRequetes}>
      <MemoryRouter initialEntries={["/organisateur/evenements/nouveau"]}>
        <Routes>
          <Route path="/organisateur/evenements/nouveau" element={<PageNouvelEvenement />} />
          <Route
            path="/organisateur/evenements/:evenementId"
            element={<h1>Gérer l'événement de test</h1>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("test_un_nom_refuse_en_422_s_affiche_sous_le_champ_nom", async () => {
  serveurMsw.use(
    http.post("*/api/v1/events", () =>
      HttpResponse.json<Probleme>(
        {
          type: "about:blank",
          title: "Requête invalide",
          status: 422,
          detail: "Le corps de la requête est invalide.",
          code: "REQUETE_INVALIDE",
          erreurs: [{ champ: "body.nom", message: "Nom de test requis." }],
        },
        { status: 422, headers: { "Content-Type": "application/problem+json" } },
      ),
    ),
  );
  const utilisateur = userEvent.setup();
  rendrePage();

  await utilisateur.click(screen.getByRole("button", { name: "Créer" }));

  await screen.findByText("Nom de test requis.");
  const nom = screen.getByLabelText(/^Nom/);
  expect(nom).toHaveAttribute("aria-invalid", "true");
  expect(nom).toHaveAccessibleDescription("Nom de test requis.");
  expect(screen.getByLabelText(/^Description/)).not.toHaveAttribute("aria-invalid");
  expect(screen.getByRole("alert")).not.toHaveTextContent("Nom de test requis.");
});

it("test_un_evenement_cree_mene_a_sa_page_de_gestion", async () => {
  let corps: EvenementCreation | null = null;
  serveurMsw.use(
    http.post("*/api/v1/events", async ({ request }) => {
      corps = (await request.json()) as EvenementCreation;
      return HttpResponse.json<Evenement>(
        { id: EVENEMENT_ID, ...corps, cree_le: "2026-11-15T10:00:00+01:00" },
        { status: 201 },
      );
    }),
  );
  const utilisateur = userEvent.setup();
  rendrePage();

  await utilisateur.type(screen.getByLabelText(/^Nom/), "Festival de test");
  await utilisateur.type(screen.getByLabelText(/^Description/), "Description synthétique.");
  await utilisateur.click(screen.getByRole("button", { name: "Créer" }));

  expect(
    await screen.findByRole("heading", { name: "Gérer l'événement de test" }),
  ).toBeInTheDocument();
  expect(corps).toEqual({ nom: "Festival de test", description: "Description synthétique." });
});
