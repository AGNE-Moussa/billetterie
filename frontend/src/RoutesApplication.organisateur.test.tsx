// Cas composant de BIL-022 (CA1) : un client, un revendeur ou un utilisateur sans rôle ne voit
// jamais l'espace organisateur (E10 à E15) : ni la page, ni le lien de navigation, ni aucune
// requête de ses écrans ; l'administrateur y accède. Table des routes de l'application sous
// MemoryRouter, session imposée par le contexte, API simulée par MSW.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router";

import type { EvenementPage, LieuPage } from "./api/genere/catalogue";
import type { Role } from "./auth/roles";
import { ContexteSession, SESSION_NON_CONNECTEE, type Session } from "./auth/session";
import { serveurMsw } from "./mocks/serveur";
import { RoutesApplication } from "./RoutesApplication";

const EVENEMENT_ID = "e0e00000-0000-4000-8000-000000000001";
const SEANCE_ID = "5e0a0000-0000-4000-8000-000000000001";

const ROUTES_ORGANISATEUR = [
  "/organisateur",
  "/organisateur/evenements/nouveau",
  `/organisateur/evenements/${EVENEMENT_ID}`,
  `/organisateur/evenements/${EVENEMENT_ID}/seances/nouvelle`,
  `/organisateur/seances/${SEANCE_ID}`,
  "/organisateur/lieux",
];

/** Toute requête vers l'API, notée : un écran organisateur rendu en appellerait. */
let requetesApi: string[] = [];

function simulerApi() {
  serveurMsw.use(
    http.get("*/api/v1/events", ({ request }) => {
      requetesApi.push(request.url);
      return HttpResponse.json<EvenementPage>({ elements: [], page: 1, size: 20, total: 0 });
    }),
    http.get("*/api/v1/venues", ({ request }) => {
      requetesApi.push(request.url);
      return HttpResponse.json<LieuPage>({ elements: [], page: 1, size: 20, total: 0 });
    }),
    http.all("*/api/v1/*", ({ request }) => {
      requetesApi.push(request.url);
      return HttpResponse.json({}, { status: 500 });
    }),
  );
}

function sessionDe(roles: Role[]): Session {
  return {
    ...SESSION_NON_CONNECTEE,
    statut: "connecte",
    nomUtilisateur: "test.utilisateur",
    roles,
  };
}

function rendreA(chemin: string, session: Session) {
  const clientRequetes = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={clientRequetes}>
      <ContexteSession.Provider value={session}>
        <MemoryRouter initialEntries={[chemin]}>
          <RoutesApplication />
        </MemoryRouter>
      </ContexteSession.Provider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  requetesApi = [];
});

const ROLES_REFUSES: { cas: string; roles: Role[] }[] = [
  { cas: "client", roles: ["customer"] },
  { cas: "revendeur", roles: ["partner"] },
  { cas: "client et revendeur", roles: ["customer", "partner"] },
  { cas: "sans rôle", roles: [] },
];

describe.each(ROLES_REFUSES)("rôle $cas", ({ roles }) => {
  it.each(ROUTES_ORGANISATEUR)(
    "test_l_espace_organisateur_est_refuse_sans_le_role_admin (%s)",
    async (chemin) => {
      simulerApi();
      rendreA(chemin, sessionDe(roles));

      expect(
        await screen.findByRole("heading", { level: 1, name: "Accès refusé" }),
      ).toBeInTheDocument();
      expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
      expect(screen.queryByRole("link", { name: "Espace organisateur" })).not.toBeInTheDocument();
      expect(requetesApi).toEqual([]);
    },
  );
});

it("test_l_administrateur_voit_l_espace_organisateur_et_son_lien", async () => {
  simulerApi();
  rendreA("/organisateur", sessionDe(["admin"]));

  expect(
    await screen.findByRole("heading", { level: 1, name: "Espace organisateur" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Espace organisateur" })).toHaveAttribute(
    "href",
    "/organisateur",
  );
});

it("test_le_lien_espace_organisateur_n_apparait_pas_pour_un_client_sur_le_catalogue", async () => {
  simulerApi();
  rendreA("/", sessionDe(["customer"]));

  await screen.findByRole("heading", { level: 1, name: "Événements" });

  expect(screen.getByRole("link", { name: "Mes commandes" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Espace organisateur" })).not.toBeInTheDocument();
});
