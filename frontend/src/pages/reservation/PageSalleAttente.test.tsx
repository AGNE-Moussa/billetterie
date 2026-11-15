// Cas composant de BIL-023 (E16) : rafraîchir la page ne fait pas perdre sa place (chaque
// ouverture redemande sa place par `entrerFile`, idempotent côté serveur, CA1) ; interrogation
// de la position bornée entre 5 et 30 secondes (quart de l'attente estimée) ; admission vers le
// plan de salle avec la sélection ; séance sans file vers le plan ; place perdue (404
// QUEUE_POSITION_NOT_FOUND) : « Reprendre une place ». API simulée par MSW, minuteries simulées.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";

import type { Evenement, Probleme, Seance } from "../../api/genere/catalogue";
import type { PositionFile } from "../../api/genere/file-attente";
import { ContexteSession, SESSION_NON_CONNECTEE, type Session } from "../../auth/session";
import { serveurMsw } from "../../mocks/serveur";
import { PageSalleAttente } from "./PageSalleAttente";

const SEANCE_ID = "5e0a0000-0000-4000-8000-000000000001";
const SEANCE: Seance = {
  id: SEANCE_ID,
  evenement_id: "e0e00000-0000-4000-8000-000000000001",
  lieu_id: "11e00000-0000-4000-8000-000000000001",
  debut: "2026-12-12T20:00:00+01:00",
  annulee: false,
  categories: [],
};
const EVENEMENT: Evenement = {
  id: SEANCE.evenement_id,
  nom: "Concert de test",
  description: "Description synthétique.",
  cree_le: "2026-10-01T10:00:00+02:00",
};

const SESSION_CLIENT: Session = {
  ...SESSION_NON_CONNECTEE,
  statut: "connecte",
  nomUtilisateur: "client.test",
  roles: ["customer"],
};

function enAttente(position: number, attente: number): PositionFile {
  return {
    seance_id: SEANCE_ID,
    statut: "EN_ATTENTE",
    position,
    attente_estimee_secondes: attente,
    jeton_admission: null,
    admission_expire_le: null,
  };
}

function admis(): PositionFile {
  return {
    seance_id: SEANCE_ID,
    statut: "ADMIS",
    position: null,
    attente_estimee_secondes: null,
    jeton_admission: `jeton-admission-de-test-${crypto.randomUUID()}`,
    admission_expire_le: new Date(Date.now() + 5 * 60 * 1000).toISOString(),
  };
}

function reponseProbleme(status: number, code: string, title: string) {
  return HttpResponse.json<Probleme>(
    { type: "about:blank", title, status, detail: `Détail de test ${code}.`, code },
    { status, headers: { "Content-Type": "application/problem+json" } },
  );
}

/** Requêtes vers la file, dans l'ordre : méthode et instant (horloge du test). */
let requetesFile: { methode: "POST" | "GET"; instant: number }[] = [];

function simulerFile(options: { entrer: () => Response; lire?: () => Response }) {
  serveurMsw.use(
    http.get("*/api/v1/shows/:seanceId", () => HttpResponse.json<Seance>(SEANCE)),
    http.get("*/api/v1/events/:evenementId", () => HttpResponse.json<Evenement>(EVENEMENT)),
    http.post("*/api/v1/queues/:seanceId/position", () => {
      requetesFile.push({ methode: "POST", instant: Date.now() });
      return options.entrer();
    }),
    http.get("*/api/v1/queues/:seanceId/position", () => {
      requetesFile.push({ methode: "GET", instant: Date.now() });
      return (options.lire ?? options.entrer)();
    }),
  );
}

function TemoinAdresse() {
  const { pathname, search } = useLocation();
  return <p data-testid="adresse">{`${pathname}${search}`}</p>;
}

function adresse(): URL {
  return new URL(screen.getByTestId("adresse").textContent ?? "", window.location.origin);
}

/** Une ouverture de la page : nouveau cache, comme après un rafraîchissement du navigateur. */
function ouvrir(chemin = `/seances/${SEANCE_ID}/attente`) {
  const clientRequetes = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={clientRequetes}>
      <ContexteSession.Provider value={SESSION_CLIENT}>
        <MemoryRouter initialEntries={[chemin]}>
          <Routes>
            <Route path="/seances/:seanceId/attente" element={<PageSalleAttente />} />
            <Route path="/seances/:seanceId" element={<h1>Plan de salle de test</h1>} />
          </Routes>
          <TemoinAdresse />
        </MemoryRouter>
      </ContexteSession.Provider>
    </QueryClientProvider>,
  );
}

function ecartsEntreLectures(): number[] {
  const instants = requetesFile.map((requete) => requete.instant);
  return instants.slice(1).map((instant, indice) => instant - (instants[indice] ?? instant));
}

beforeEach(() => {
  requetesFile = [];
});

afterEach(() => {
  vi.useRealTimers();
});

it("test_la_position_et_l_attente_estimee_sont_annoncees_avec_une_barre_de_progression", async () => {
  simulerFile({ entrer: () => HttpResponse.json<PositionFile>(enAttente(1254, 360)) });
  ouvrir();

  expect(
    await screen.findByText(/Position : 1\s254 - Attente estimée : environ 6 min/),
  ).toHaveAttribute("role", "status");
  expect(
    screen.getByRole("progressbar", { name: "Progression dans la file d'attente" }),
  ).toBeInTheDocument();
});

it("test_rafraichir_la_page_redemande_sa_place_par_entrer_file_et_retrouve_la_meme_position", async () => {
  // Serveur idempotent : le même appelant garde sa position.
  simulerFile({ entrer: () => HttpResponse.json<PositionFile>(enAttente(42, 600)) });
  const premiere = ouvrir();
  expect(await screen.findByText(/Position : 42 /)).toBeInTheDocument();

  premiere.unmount();
  ouvrir();

  expect(await screen.findByText(/Position : 42 /)).toBeInTheDocument();
  expect(requetesFile.map((requete) => requete.methode)).toEqual(["POST", "POST"]);
});

it.each([
  {
    cas: "attente courte : 5 s au moins",
    attente: 8,
    minimum: 5_000,
    maximum: 5_500,
    duree: 21_000,
  },
  {
    cas: "attente de 1 min : quart, 15 s",
    attente: 60,
    minimum: 15_000,
    maximum: 15_500,
    duree: 46_000,
  },
  {
    cas: "attente longue : 30 s au plus",
    attente: 3_600,
    minimum: 30_000,
    maximum: 30_500,
    duree: 91_000,
  },
])(
  "test_la_position_est_relue_a_un_intervalle_borne_entre_5_et_30_secondes ($cas)",
  async ({ attente, minimum, maximum, duree }) => {
    vi.useFakeTimers({
      shouldAdvanceTime: true,
      toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"],
    });
    simulerFile({ entrer: () => HttpResponse.json<PositionFile>(enAttente(42, attente)) });
    ouvrir();
    await screen.findByText(/Position : 42 /);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(duree);
    });

    expect(requetesFile[0]?.methode).toBe("POST");
    const lectures = requetesFile.slice(1);
    expect(lectures.length).toBeGreaterThanOrEqual(3);
    expect(lectures.every((requete) => requete.methode === "GET")).toBe(true);
    for (const ecart of ecartsEntreLectures()) {
      expect(ecart).toBeGreaterThanOrEqual(minimum);
      expect(ecart).toBeLessThanOrEqual(maximum);
    }
  },
);

it("test_a_l_admission_le_client_est_redirige_vers_le_plan_de_salle_avec_sa_selection", async () => {
  let lectures = 0;
  simulerFile({
    entrer: () => HttpResponse.json<PositionFile>(enAttente(1, 4)),
    lire: () => {
      lectures += 1;
      return HttpResponse.json<PositionFile>(admis());
    },
  });
  ouvrir(`/seances/${SEANCE_ID}/attente?places=a1`);
  await screen.findByText(/Position : 1 /);

  expect(
    await screen.findByRole("heading", { name: "Plan de salle de test" }, { timeout: 8_000 }),
  ).toBeInTheDocument();
  expect(lectures).toBe(1);
  expect(adresse().pathname).toBe(`/seances/${SEANCE_ID}`);
  expect(adresse().searchParams.get("places")).toBe("a1");
});

it("test_une_seance_sans_file_ouvre_directement_le_plan_de_salle", async () => {
  simulerFile({ entrer: () => reponseProbleme(404, "QUEUE_NOT_FOUND", "Aucune file") });
  ouvrir();

  expect(await screen.findByRole("heading", { name: "Plan de salle de test" })).toBeInTheDocument();
  expect(adresse().pathname).toBe(`/seances/${SEANCE_ID}`);
});

it("test_une_place_perdue_propose_de_reprendre_une_place_par_entrer_file", async () => {
  simulerFile({
    entrer: () => HttpResponse.json<PositionFile>(enAttente(3, 4)),
    lire: () => reponseProbleme(404, "QUEUE_POSITION_NOT_FOUND", "Hors de la file"),
  });
  const utilisateur = userEvent.setup();
  ouvrir();

  const reprendre = await screen.findByRole(
    "button",
    { name: "Reprendre une place dans la file" },
    { timeout: 8_000 },
  );
  expect(screen.getByRole("alert")).toHaveTextContent("Vous n'êtes plus dans la file d'attente.");
  await utilisateur.click(reprendre);

  await waitFor(() =>
    expect(requetesFile.map((requete) => requete.methode)).toEqual(["POST", "GET", "POST"]),
  );
});

it("test_une_file_indisponible_affiche_l_erreur_et_reessayer", async () => {
  let echec = true;
  simulerFile({
    entrer: () =>
      echec
        ? reponseProbleme(503, "SERVICE_INDISPONIBLE", "File momentanément indisponible")
        : HttpResponse.json<PositionFile>(enAttente(7, 600)),
  });
  const utilisateur = userEvent.setup();
  ouvrir();

  expect(await screen.findByRole("alert")).toHaveTextContent("File momentanément indisponible");
  echec = false;
  await utilisateur.click(screen.getByRole("button", { name: "Réessayer" }));

  expect(await screen.findByText(/Position : 7 /)).toBeInTheDocument();
});
