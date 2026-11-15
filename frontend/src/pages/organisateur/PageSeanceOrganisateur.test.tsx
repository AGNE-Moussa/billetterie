// Cas composant de BIL-022 (E14) : annulation d'une séance avec confirmation explicite (aucune
// requête avant « Confirmer l'annulation », « Garder la séance » n'annule rien), bouton retiré
// après succès ; 409 SHOW_ALREADY_STARTED : message et séance relue ; remplissage par catégorie
// calculé sur les places. API simulée par MSW ; données synthétiques.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";

import type { Place, PlacePage } from "../../api/genere/billets";
import type { Evenement, Lieu, Probleme, Seance } from "../../api/genere/catalogue";
import { serveurMsw } from "../../mocks/serveur";
import { PageSeanceOrganisateur } from "./PageSeanceOrganisateur";

// Bouchon minimal de HTMLDialogElement.showModal / close, absents de jsdom (même principe que
// DialogueConfirmation.test.tsx) : `open` posé ou retiré, événement `close` émis.
if (typeof HTMLDialogElement.prototype.showModal !== "function") {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    if (!this.open) return;
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
}

const OR = {
  id: "ca7e0000-0000-4000-8000-00000000000a",
  nom: "Or",
  prix: 4500,
  rangs: [{ rang: "A", nombre_places: 3 }],
};
const SEANCE: Seance = {
  id: "5e0a0000-0000-4000-8000-000000000001",
  evenement_id: "e0e00000-0000-4000-8000-000000000001",
  lieu_id: "11e00000-0000-4000-8000-000000000001",
  debut: "2026-12-12T20:00:00+01:00",
  annulee: false,
  categories: [OR],
};
const PLACES: Place[] = [1, 2, 3].map((numero) => ({
  id: `a${String(numero)}000000-0000-4000-8000-000000000000`,
  seance_id: SEANCE.id,
  rang: "A",
  numero,
  categorie_id: OR.id,
  disponible: numero === 3,
}));

let seanceCourante: Seance;
let lecturesSeance = 0;
let annulations = 0;

function simulerApi(annuler: () => Response) {
  serveurMsw.use(
    http.get("*/api/v1/shows/:seanceId", () => {
      lecturesSeance += 1;
      return HttpResponse.json<Seance>(seanceCourante);
    }),
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
      HttpResponse.json<PlacePage>({ elements: PLACES, page: 1, size: 100, total: PLACES.length }),
    ),
    http.post("*/api/v1/events/:evenementId/shows/:seanceId/cancellation", () => {
      annulations += 1;
      return annuler();
    }),
  );
}

function rendrePage() {
  const clientRequetes = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={clientRequetes}>
      <MemoryRouter initialEntries={[`/organisateur/seances/${SEANCE.id}`]}>
        <Routes>
          <Route path="/organisateur/seances/:seanceId" element={<PageSeanceOrganisateur />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function boutonAnnuler() {
  const bouton = await screen.findByRole("button", { name: "Annuler la séance" });
  // Le bouton n'est actif qu'une fois l'événement de la séance connu.
  await waitFor(() => expect(bouton).not.toHaveAttribute("aria-disabled"));
  return bouton;
}

beforeEach(() => {
  seanceCourante = SEANCE;
  lecturesSeance = 0;
  annulations = 0;
});

it("test_le_remplissage_compte_les_places_prises_par_categorie", async () => {
  simulerApi(() => HttpResponse.json<Seance>({ ...SEANCE, annulee: true }));
  rendrePage();

  const tableau = await screen.findByRole("table", { name: "Remplissage par catégorie" });
  const ligneOr = within(tableau).getByRole("row", { name: /^Or/ });
  expect(
    within(ligneOr)
      .getAllByRole("cell")
      .map((cellule) => cellule.textContent),
  ).toEqual(["2", "3"]);
});

it("test_annuler_une_seance_demande_une_confirmation_explicite_avant_tout_appel", async () => {
  simulerApi(() => {
    seanceCourante = { ...SEANCE, annulee: true };
    return HttpResponse.json<Seance>(seanceCourante);
  });
  const utilisateur = userEvent.setup();
  rendrePage();

  await utilisateur.click(await boutonAnnuler());
  const dialogue = await screen.findByRole("dialog", { name: /^Annuler la séance du / });
  expect(dialogue).toHaveAccessibleDescription(
    "Tous les acheteurs seront remboursés et prévenus, et leurs billets annulés.",
  );
  expect(annulations).toBe(0);

  await utilisateur.click(within(dialogue).getByRole("button", { name: "Garder la séance" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(annulations).toBe(0);

  await utilisateur.click(await boutonAnnuler());
  await utilisateur.click(
    within(await screen.findByRole("dialog")).getByRole("button", {
      name: "Confirmer l'annulation",
    }),
  );

  expect(await screen.findByText("Séance annulée.")).toBeInTheDocument();
  expect(annulations).toBe(1);
  expect(screen.queryByRole("button", { name: "Annuler la séance" })).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("test_une_seance_deja_commencee_affiche_le_refus_et_relit_la_seance", async () => {
  simulerApi(() =>
    HttpResponse.json<Probleme>(
      {
        type: "about:blank",
        title: "Séance déjà commencée",
        status: 409,
        detail: "Détail de test SHOW_ALREADY_STARTED.",
        code: "SHOW_ALREADY_STARTED",
      },
      { status: 409, headers: { "Content-Type": "application/problem+json" } },
    ),
  );
  const utilisateur = userEvent.setup();
  rendrePage();
  await utilisateur.click(await boutonAnnuler());
  const lecturesAvant = lecturesSeance;

  await utilisateur.click(
    within(await screen.findByRole("dialog")).getByRole("button", {
      name: "Confirmer l'annulation",
    }),
  );

  expect(await screen.findByRole("alert")).toHaveTextContent("Séance déjà commencée");
  await waitFor(() => expect(lecturesSeance).toBeGreaterThan(lecturesAvant));
  expect(annulations).toBe(1);
});
