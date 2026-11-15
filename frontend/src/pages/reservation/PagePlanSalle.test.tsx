// Cas composant de BIL-020 (E03) et BIL-023 (file d'attente) : réservation sans carte avec
// Idempotency-Key (clé gardée pour rejouer la même sélection après une panne réseau), 409
// SEAT_ALREADY_TAKEN signalé sans casser la page, plan relu et sélection gardée sans la place
// perdue (CA1 de BIL-020) ; séance sous file : EN_ATTENTE vers E16, ADMIS avec
// X-Admission-Token, 403 ADMISSION_* de retour sur E16 avec un message, jeton d'admission jamais
// dans le stockage du navigateur. Session imposée par le contexte ; API simulée par MSW.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";

import type { Place, PlacePage } from "../../api/genere/billets";
import type { Evenement, Lieu, Probleme, Seance } from "../../api/genere/catalogue";
import type { Commande } from "../../api/genere/commandes";
import type { PositionFile } from "../../api/genere/file-attente";
import type { Role } from "../../auth/roles";
import { ContexteSession, SESSION_NON_CONNECTEE, type Session } from "../../auth/session";
import { serveurMsw } from "../../mocks/serveur";
import { PagePlanSalle } from "./PagePlanSalle";
import { PageSalleAttente } from "./PageSalleAttente";

const FORMAT_UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const SEANCE_ID = "5e0a0000-0000-4000-8000-000000000001";
const COMMANDE_ID = "c0de0000-0000-4000-8000-000000000001";
const JETON_ADMISSION = `jeton-admission-de-test-${crypto.randomUUID()}`;

const OR = {
  id: "ca7e0000-0000-4000-8000-00000000000a",
  nom: "Or",
  prix: 4500,
  rangs: [{ rang: "A", nombre_places: 3 }],
};
const SEANCE: Seance = {
  id: SEANCE_ID,
  evenement_id: "e0e00000-0000-4000-8000-000000000001",
  lieu_id: "11e00000-0000-4000-8000-000000000001",
  debut: "2026-12-12T20:00:00+01:00",
  annulee: false,
  categories: [OR],
};
const EVENEMENT: Evenement = {
  id: SEANCE.evenement_id,
  nom: "Concert de test",
  description: "Description synthétique.",
  cree_le: "2026-10-01T10:00:00+02:00",
};
const LIEU: Lieu = {
  id: SEANCE.lieu_id,
  nom: "Salle de test",
  adresse: "1 rue de l'Exemple",
  ville: "Lyon",
  cree_le: "2026-10-01T10:00:00+02:00",
};

function place(numero: number, disponible = true): Place {
  return {
    id: `a${String(numero)}000000-0000-4000-8000-000000000000`,
    seance_id: SEANCE_ID,
    rang: "A",
    numero,
    categorie_id: OR.id,
    disponible,
  };
}

const [A1, A2, A3] = [place(1), place(2), place(3)];

function reponseProbleme(status: number, code: string, title: string) {
  return HttpResponse.json<Probleme>(
    { type: "about:blank", title, status, detail: `Détail de test ${code}.`, code },
    { status, headers: { "Content-Type": "application/problem+json" } },
  );
}

function commandeEnAttente(placeIds: string[]): Commande {
  return {
    id: COMMANDE_ID,
    seance_id: SEANCE_ID,
    lignes: placeIds.map((place_id) => ({ place_id, montant: OR.prix })),
    statut: "EN_ATTENTE",
    montant_total: OR.prix * placeIds.length,
    cree_le: new Date().toISOString(),
    expire_le: new Date(Date.now() + 10 * 60 * 1000).toISOString(),
  };
}

interface RequeteCommande {
  idempotence: string | null;
  admission: string | null;
  corps: { seance_id: string; place_ids: string[]; carte_test: string | null };
}

let lecturesPlaces = 0;
let requetesCommande: RequeteCommande[] = [];
let entreesFile = 0;

/** Catalogue et places ; `places` : la réponse de chaque lecture successive du plan. */
function simulerSeance(places: (lecture: number) => Place[]) {
  serveurMsw.use(
    http.get("*/api/v1/shows/:seanceId", () => HttpResponse.json<Seance>(SEANCE)),
    http.get("*/api/v1/events/:evenementId", () => HttpResponse.json<Evenement>(EVENEMENT)),
    http.get("*/api/v1/venues/:lieuId", () => HttpResponse.json<Lieu>(LIEU)),
    http.get("*/api/v1/seats", () => {
      lecturesPlaces += 1;
      const elements = places(lecturesPlaces);
      return HttpResponse.json<PlacePage>({ elements, page: 1, size: 100, total: elements.length });
    }),
  );
}

function simulerFile(repondre: () => Response) {
  serveurMsw.use(
    http.post("*/api/v1/queues/:seanceId/position", () => {
      entreesFile += 1;
      return repondre();
    }),
  );
}

function sansFile() {
  simulerFile(() => reponseProbleme(404, "QUEUE_NOT_FOUND", "Aucune file pour cette séance"));
}

function admis(): PositionFile {
  return {
    seance_id: SEANCE_ID,
    statut: "ADMIS",
    position: null,
    attente_estimee_secondes: null,
    jeton_admission: JETON_ADMISSION,
    admission_expire_le: new Date(Date.now() + 5 * 60 * 1000).toISOString(),
  };
}

function simulerCommande(repondre: (requete: RequeteCommande) => Response) {
  serveurMsw.use(
    http.post("*/api/v1/orders", async ({ request }) => {
      const requete: RequeteCommande = {
        idempotence: request.headers.get("Idempotency-Key"),
        admission: request.headers.get("X-Admission-Token"),
        corps: (await request.json()) as RequeteCommande["corps"],
      };
      requetesCommande.push(requete);
      return repondre(requete);
    }),
  );
}

function sessionDe(roles: Role[]): Session {
  return { ...SESSION_NON_CONNECTEE, statut: "connecte", nomUtilisateur: "client.test", roles };
}

function TemoinAdresse() {
  const { pathname, search } = useLocation();
  return <p data-testid="adresse">{`${pathname}${search}`}</p>;
}

function adresse(): URL {
  return new URL(screen.getByTestId("adresse").textContent ?? "", window.location.origin);
}

function rendreA(chemin: string, session: Session = sessionDe(["customer"])) {
  const clientRequetes = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={clientRequetes}>
      <ContexteSession.Provider value={session}>
        <MemoryRouter initialEntries={[chemin]}>
          <Routes>
            <Route path="/seances/:seanceId" element={<PagePlanSalle />} />
            <Route path="/seances/:seanceId/attente" element={<PageSalleAttente />} />
            <Route path="/commandes/:commandeId/paiement" element={<h1>Paiement de test</h1>} />
          </Routes>
          <TemoinAdresse />
        </MemoryRouter>
      </ContexteSession.Provider>
    </QueryClientProvider>,
  );
}

function boutonPlace(numero: number) {
  return screen.getByRole("button", { name: new RegExp(`^Rang A, place ${String(numero)},`) });
}

async function attendrePlan() {
  await screen.findByRole("grid");
  await screen.findByRole("heading", { level: 1, name: EVENEMENT.nom });
}

beforeEach(() => {
  lecturesPlaces = 0;
  requetesCommande = [];
  entreesFile = 0;
});

afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------------------------
// BIL-020 : réservation sans carte.

it("test_reserver_cree_une_commande_sans_carte_avec_une_idempotency_key_puis_mene_au_paiement", async () => {
  simulerSeance(() => [A1, A2, A3]);
  sansFile();
  simulerCommande(({ corps }) =>
    HttpResponse.json<Commande>(commandeEnAttente(corps.place_ids), { status: 201 }),
  );
  const utilisateur = userEvent.setup();
  rendreA(`/seances/${SEANCE_ID}`);
  await attendrePlan();

  await utilisateur.click(boutonPlace(1));
  await utilisateur.click(boutonPlace(3));
  await utilisateur.click(await screen.findByRole("button", { name: "Réserver ces places" }));

  expect(await screen.findByRole("heading", { name: "Paiement de test" })).toBeInTheDocument();
  expect(adresse().pathname).toBe(`/commandes/${COMMANDE_ID}/paiement`);
  expect(requetesCommande).toHaveLength(1);
  const [requete] = requetesCommande;
  expect(requete?.corps).toEqual({
    seance_id: SEANCE_ID,
    place_ids: [A1.id, A3.id],
    carte_test: null,
  });
  expect(requete?.idempotence).toMatch(FORMAT_UUID_V4);
  expect(requete?.admission).toBeNull();
});

it("test_apres_une_panne_reseau_la_meme_selection_est_rejouee_avec_la_meme_idempotency_key", async () => {
  simulerSeance(() => [A1, A2, A3]);
  sansFile();
  simulerCommande(({ corps }) =>
    requetesCommande.length === 1
      ? HttpResponse.error()
      : HttpResponse.json<Commande>(commandeEnAttente(corps.place_ids), { status: 201 }),
  );
  const utilisateur = userEvent.setup();
  rendreA(`/seances/${SEANCE_ID}?places=${A1.id}`);
  await attendrePlan();

  await utilisateur.click(screen.getByRole("button", { name: "Réserver cette place" }));
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  await utilisateur.click(screen.getByRole("button", { name: "Réserver cette place" }));

  await screen.findByRole("heading", { name: "Paiement de test" });
  expect(requetesCommande).toHaveLength(2);
  expect(requetesCommande[1]?.idempotence).toBe(requetesCommande[0]?.idempotence);
});

it("test_une_place_prise_entre_temps_est_signalee_le_plan_relu_et_la_selection_gardee_sans_elle", async () => {
  // Deuxième lecture du plan : A2 vient d'être prise par un autre client.
  simulerSeance((lecture) => (lecture === 1 ? [A1, A2, A3] : [A1, place(2, false), A3]));
  sansFile();
  simulerCommande(() => reponseProbleme(409, "SEAT_ALREADY_TAKEN", "Place déjà prise"));
  const utilisateur = userEvent.setup();
  rendreA(`/seances/${SEANCE_ID}?places=${A1.id},${A2.id}`);
  await attendrePlan();

  await utilisateur.click(screen.getByRole("button", { name: "Réserver ces places" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Une place vient d'être prise.");
  await waitFor(() => expect(boutonPlace(2)).toHaveAccessibleName(/, indisponible$/));
  expect(lecturesPlaces).toBe(2);
  await waitFor(() => expect(adresse().searchParams.get("places")).toBe(A1.id));
  expect(boutonPlace(1)).toHaveAccessibleName(/, sélectionnée$/);
  // La page reste utilisable : titre, plan et bouton de réservation.
  expect(screen.getByRole("heading", { level: 1, name: EVENEMENT.nom })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Réserver cette place" })).toBeInTheDocument();
});

it("test_un_visiteur_non_connecte_voit_le_plan_et_se_connecte_pour_reserver_avec_sa_selection", async () => {
  simulerSeance(() => [A1, A2, A3]);
  const seConnecter = vi.fn<Session["seConnecter"]>().mockResolvedValue(true);
  const utilisateur = userEvent.setup();
  rendreA(`/seances/${SEANCE_ID}?places=${A3.id}`, { ...SESSION_NON_CONNECTEE, seConnecter });
  await attendrePlan();

  await utilisateur.click(screen.getByRole("button", { name: "Se connecter pour réserver" }));

  expect(seConnecter).toHaveBeenCalledWith(`/seances/${SEANCE_ID}?places=${A3.id}`);
  expect(entreesFile).toBe(0);
  expect(requetesCommande).toHaveLength(0);
});

// ---------------------------------------------------------------------------------------------
// BIL-023 : séance sous file d'attente.

it("test_un_client_en_attente_dans_la_file_est_envoye_en_salle_d_attente_avec_sa_selection", async () => {
  simulerSeance(() => [A1, A2, A3]);
  simulerFile(() =>
    HttpResponse.json<PositionFile>({
      seance_id: SEANCE_ID,
      statut: "EN_ATTENTE",
      position: 12,
      attente_estimee_secondes: 120,
      jeton_admission: null,
      admission_expire_le: null,
    }),
  );
  serveurMsw.use(
    http.get("*/api/v1/queues/:seanceId/position", () =>
      HttpResponse.json<PositionFile>({
        seance_id: SEANCE_ID,
        statut: "EN_ATTENTE",
        position: 12,
        attente_estimee_secondes: 120,
        jeton_admission: null,
        admission_expire_le: null,
      }),
    ),
  );
  rendreA(`/seances/${SEANCE_ID}?places=${A1.id}`);

  expect(
    await screen.findByRole("heading", { name: "Vous êtes dans la file d'attente" }),
  ).toBeInTheDocument();
  expect(adresse().pathname).toBe(`/seances/${SEANCE_ID}/attente`);
  expect(adresse().searchParams.get("places")).toBe(A1.id);
});

it("test_un_client_admis_envoie_son_jeton_dans_x_admission_token_sans_le_stocker", async () => {
  const ecritures = vi.spyOn(Storage.prototype, "setItem");
  simulerSeance(() => [A1, A2, A3]);
  simulerFile(() => HttpResponse.json<PositionFile>(admis()));
  simulerCommande(({ corps }) =>
    HttpResponse.json<Commande>(commandeEnAttente(corps.place_ids), { status: 201 }),
  );
  const utilisateur = userEvent.setup();
  rendreA(`/seances/${SEANCE_ID}?places=${A1.id}`);
  await attendrePlan();

  expect(await screen.findByText(/Admission valable jusqu'à/)).toBeInTheDocument();
  await utilisateur.click(screen.getByRole("button", { name: "Réserver cette place" }));

  await screen.findByRole("heading", { name: "Paiement de test" });
  expect(requetesCommande[0]?.admission).toBe(JETON_ADMISSION);
  // Jeton gardé en mémoire de l'onglet seulement.
  for (const [cle, valeur] of ecritures.mock.calls) {
    expect(`${cle} ${valeur}`).not.toContain(JETON_ADMISSION);
  }
  for (const stockage of [localStorage, sessionStorage]) {
    for (let indice = 0; indice < stockage.length; indice += 1) {
      const cle = stockage.key(indice) ?? "";
      expect(`${cle} ${stockage.getItem(cle) ?? ""}`).not.toContain(JETON_ADMISSION);
    }
  }
  expect(document.cookie).not.toContain(JETON_ADMISSION);
});

it.each(["ADMISSION_REQUIRED", "ADMISSION_INVALID"])(
  "test_un_refus_d_admission_%s_ramene_en_salle_d_attente_avec_un_message",
  async (code) => {
    simulerSeance(() => [A1, A2, A3]);
    simulerFile(() => HttpResponse.json<PositionFile>(admis()));
    simulerCommande(() => reponseProbleme(403, code, "Admission refusée"));
    const utilisateur = userEvent.setup();
    rendreA(`/seances/${SEANCE_ID}?places=${A1.id}`);
    await attendrePlan();
    await screen.findByText(/Admission valable jusqu'à/);

    await utilisateur.click(screen.getByRole("button", { name: "Réserver cette place" }));

    const message = await screen.findByText(
      /^Votre admission n'a pas été acceptée pour la réservation/,
    );
    expect(message.closest("[role='alert']")).not.toBeNull();
    expect(adresse().pathname).toBe(`/seances/${SEANCE_ID}/attente`);
    expect(adresse().searchParams.get("places")).toBe(A1.id);
    // La salle d'attente redemande sa place à la file (entrerFile), sans renvoi automatique.
    await waitFor(() => expect(entreesFile).toBe(2));
    expect(await screen.findByRole("link", { name: "Aller au plan de salle" })).toBeInTheDocument();
  },
);

it("test_une_file_en_panne_laisse_la_reservation_possible", async () => {
  simulerSeance(() => [A1, A2, A3]);
  simulerFile(() =>
    reponseProbleme(503, "SERVICE_INDISPONIBLE", "File momentanément indisponible"),
  );
  simulerCommande(({ corps }) =>
    HttpResponse.json<Commande>(commandeEnAttente(corps.place_ids), { status: 201 }),
  );
  const utilisateur = userEvent.setup();
  rendreA(`/seances/${SEANCE_ID}?places=${A1.id}`);
  await attendrePlan();

  expect(
    await screen.findByText(/L'accès à cette séance n'a pas pu être vérifié/),
  ).toBeInTheDocument();
  await utilisateur.click(screen.getByRole("button", { name: "Réserver cette place" }));

  await screen.findByRole("heading", { name: "Paiement de test" });
  expect(requetesCommande[0]?.admission).toBeNull();
});
