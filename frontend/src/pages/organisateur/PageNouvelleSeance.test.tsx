// Cas composant de BIL-022 (CA2, E13) : les erreurs de validation de l'API (422
// REQUETE_INVALIDE, `erreurs[].champ` au format « body.categories.0.prix ») s'affichent sous
// chaque champ, champs imbriqués compris (catégorie, rang) ; une erreur sans champ affiché reste
// dans le résumé ; SHOW_START_IN_PAST sous la date. API simulée par MSW ; données synthétiques.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";

import type { Evenement, LieuPage, Probleme } from "../../api/genere/catalogue";
import { serveurMsw } from "../../mocks/serveur";
import { PageNouvelleSeance } from "./PageNouvelleSeance";

const EVENEMENT: Evenement = {
  id: "e0e00000-0000-4000-8000-000000000001",
  nom: "Concert de test",
  description: "Description synthétique.",
  cree_le: "2026-10-01T10:00:00+02:00",
};
const LIEU_ID = "11e00000-0000-4000-8000-000000000001";

let corpsEnvoyes: unknown[] = [];

function simulerApi(reponseCreation: () => Response) {
  serveurMsw.use(
    http.get("*/api/v1/events/:evenementId", () => HttpResponse.json<Evenement>(EVENEMENT)),
    http.get("*/api/v1/venues", () =>
      HttpResponse.json<LieuPage>({
        elements: [
          {
            id: LIEU_ID,
            nom: "Salle de test",
            adresse: "1 rue de l'Exemple",
            ville: "Lyon",
            cree_le: "2026-10-01T10:00:00+02:00",
          },
        ],
        page: 1,
        size: 100,
        total: 1,
      }),
    ),
    http.post("*/api/v1/events/:evenementId/shows", async ({ request }) => {
      corpsEnvoyes.push(await request.json());
      return reponseCreation();
    }),
  );
}

function reponse422(probleme: Omit<Probleme, "type" | "status">) {
  return HttpResponse.json<Probleme>(
    { type: "about:blank", status: 422, ...probleme },
    { status: 422, headers: { "Content-Type": "application/problem+json" } },
  );
}

function rendrePage() {
  const clientRequetes = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={clientRequetes}>
      <MemoryRouter initialEntries={[`/organisateur/evenements/${EVENEMENT.id}/seances/nouvelle`]}>
        <Routes>
          <Route
            path="/organisateur/evenements/:evenementId/seances/nouvelle"
            element={<PageNouvelleSeance />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function attendreEnErreur(champ: HTMLElement, message: string) {
  expect(champ).toHaveAttribute("aria-invalid", "true");
  expect(champ).toHaveAccessibleDescription(expect.stringContaining(message));
}

beforeEach(() => {
  corpsEnvoyes = [];
});

it("test_les_erreurs_422_s_affichent_sous_chaque_champ_y_compris_les_champs_imbriques", async () => {
  simulerApi(() =>
    reponse422({
      title: "Requête invalide",
      detail: "Le corps de la requête est invalide.",
      code: "REQUETE_INVALIDE",
      erreurs: [
        { champ: "body.lieu_id", message: "Lieu de test invalide." },
        { champ: "body.debut", message: "Début de test requis." },
        { champ: "body.categories.0.nom", message: "Nom de catégorie de test requis." },
        { champ: "body.categories.0.prix", message: "Prix de test invalide." },
        { champ: "body.categories.0.rangs.0.rang", message: "Rang de test requis." },
        {
          champ: "body.categories.0.rangs.0.nombre_places",
          message: "Nombre de places de test invalide.",
        },
        { champ: "body.champ_inconnu", message: "Erreur de test sans champ affiché." },
      ],
    }),
  );
  const utilisateur = userEvent.setup();
  rendrePage();
  await screen.findByLabelText(/^Lieu/);

  await utilisateur.click(screen.getByRole("button", { name: "Programmer" }));

  const categorie = await screen.findByRole("group", { name: "Catégorie 1" });
  await screen.findByText("Prix de test invalide.");
  attendreEnErreur(screen.getByLabelText(/^Lieu/), "Lieu de test invalide.");
  attendreEnErreur(screen.getByLabelText(/^Début/), "Début de test requis.");
  attendreEnErreur(within(categorie).getByLabelText(/^Nom/), "Nom de catégorie de test requis.");
  attendreEnErreur(within(categorie).getByLabelText(/^Prix en euros/), "Prix de test invalide.");
  attendreEnErreur(within(categorie).getByLabelText(/^Rang 1/), "Rang de test requis.");
  attendreEnErreur(
    within(categorie).getByLabelText(/^Places du rang 1/),
    "Nombre de places de test invalide.",
  );
  // Le résumé ne garde que l'erreur sans champ à l'écran.
  const resume = screen.getByRole("alert");
  expect(resume).toHaveTextContent("Requête invalide");
  expect(resume).toHaveTextContent("champ_inconnu : Erreur de test sans champ affiché.");
  expect(resume).not.toHaveTextContent("Prix de test invalide.");
  expect(corpsEnvoyes).toHaveLength(1);
});

it("test_les_erreurs_d_une_deuxieme_categorie_s_affichent_sous_ses_propres_champs", async () => {
  simulerApi(() =>
    reponse422({
      title: "Requête invalide",
      detail: "Le corps de la requête est invalide.",
      code: "REQUETE_INVALIDE",
      erreurs: [{ champ: "body.categories.1.rangs.0.nombre_places", message: "Places de test." }],
    }),
  );
  const utilisateur = userEvent.setup();
  rendrePage();
  await screen.findByLabelText(/^Lieu/);
  await utilisateur.click(screen.getByRole("button", { name: "Ajouter une catégorie" }));

  await utilisateur.click(screen.getByRole("button", { name: "Programmer" }));

  const seconde = await screen.findByRole("group", { name: "Catégorie 2" });
  await within(seconde).findByText("Places de test.");
  attendreEnErreur(within(seconde).getByLabelText(/^Places du rang 1/), "Places de test.");
  const premiere = screen.getByRole("group", { name: "Catégorie 1" });
  expect(within(premiere).getByLabelText(/^Places du rang 1/)).not.toHaveAttribute("aria-invalid");
});

it("test_un_debut_dans_le_passe_s_affiche_sous_la_date", async () => {
  simulerApi(() =>
    reponse422({
      title: "Début dans le passé",
      detail: "La séance doit commencer dans le futur.",
      code: "SHOW_START_IN_PAST",
    }),
  );
  const utilisateur = userEvent.setup();
  rendrePage();
  await screen.findByLabelText(/^Lieu/);

  await utilisateur.click(screen.getByRole("button", { name: "Programmer" }));

  await screen.findByText("La séance doit commencer dans le futur.");
  attendreEnErreur(screen.getByLabelText(/^Début/), "La séance doit commencer dans le futur.");
});
