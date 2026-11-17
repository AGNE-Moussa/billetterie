// Cas composant de BIL-020 et BIL-021 (E04) : compte à rebours calculé sur `expire_le` de l'API
// (contrainte de BIL-020), délai écoulé ; double clic sur « Payer » : un seul paiement (CA1 de
// BIL-021) ; après paiement, confirmation (E05) puis billet avec son QR code (E08, CA2 de
// BIL-021) ; paiement refusé. API simulée par MSW ; carte de test synthétique uniquement.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";

import type { Billet, BilletPage, Place, PlacePage } from "../../api/genere/billets";
import type { Evenement, Lieu, Probleme, Seance } from "../../api/genere/catalogue";
import type { Commande } from "../../api/genere/commandes";
import { PageBillet } from "../client/PageBillet";
import { PageCommande } from "../client/PageCommande";
import { serveurMsw } from "../../mocks/serveur";
import { PagePaiement } from "./PagePaiement";

const CARTE_ACCEPTEE = "4242424242424242";
const COMMANDE_ID = "c0de0000-0000-4000-8000-000000000001";
const SEANCE_ID = "5e0a0000-0000-4000-8000-000000000001";
const OR = {
  id: "ca7e0000-0000-4000-8000-00000000000a",
  nom: "Or",
  prix: 4500,
  rangs: [{ rang: "B", nombre_places: 2 }],
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
const PLACES: Place[] = [1, 2].map((numero) => ({
  id: `b${String(numero)}000000-0000-4000-8000-000000000000`,
  seance_id: SEANCE_ID,
  rang: "B",
  numero,
  categorie_id: OR.id,
  disponible: false,
}));

function commande(statut: Commande["statut"], expireDansMs = 10 * 60 * 1000): Commande {
  return {
    id: COMMANDE_ID,
    seance_id: SEANCE_ID,
    lignes: PLACES.map((place) => ({ place_id: place.id, montant: OR.prix })),
    statut,
    montant_total: OR.prix * PLACES.length,
    cree_le: new Date().toISOString(),
    expire_le: new Date(Date.now() + expireDansMs).toISOString(),
  };
}

function billet(place: Place): Billet {
  return {
    id: `b1e70000-0000-4000-8000-00000000000${String(place.numero)}`,
    commande_id: COMMANDE_ID,
    seance_id: SEANCE_ID,
    place_id: place.id,
    rang: place.rang,
    numero: place.numero,
    statut: "EMIS",
    qr_code: `qr-signe-de-test-${String(place.numero)}`,
    emis_le: new Date().toISOString(),
  };
}

function reponseProbleme(status: number, code: string, title: string) {
  return HttpResponse.json<Probleme>(
    { type: "about:blank", title, status, detail: `Détail de test ${code}.`, code },
    { status, headers: { "Content-Type": "application/problem+json" } },
  );
}

let commandeCourante: Commande;
let paiements: { carte_test: string }[] = [];

/** Commande, séance et billets ; `payer` : réponse de `payerCommande`. */
function simulerApi(payer: () => Response | Promise<Response>) {
  serveurMsw.use(
    http.get("*/api/v1/orders/:commandeId", () => HttpResponse.json<Commande>(commandeCourante)),
    http.get("*/api/v1/shows/:seanceId", () => HttpResponse.json<Seance>(SEANCE)),
    http.get("*/api/v1/events/:evenementId", () => HttpResponse.json<Evenement>(EVENEMENT)),
    http.get("*/api/v1/venues/:lieuId", () => HttpResponse.json<Lieu>(LIEU)),
    http.get("*/api/v1/seats", () =>
      HttpResponse.json<PlacePage>({ elements: PLACES, page: 1, size: 100, total: PLACES.length }),
    ),
    http.post("*/api/v1/orders/:commandeId/payment", async ({ request }) => {
      paiements.push((await request.json()) as { carte_test: string });
      return payer();
    }),
    http.get("*/api/v1/tickets", ({ request }) => {
      const commandeId = new URL(request.url).searchParams.get("commande_id");
      const elements = commandeId === COMMANDE_ID ? PLACES.map(billet) : [];
      return HttpResponse.json<BilletPage>({
        elements,
        page: 1,
        size: 100,
        total: elements.length,
      });
    }),
    http.get("*/api/v1/tickets/:billetId", ({ params }) => {
      const trouve = PLACES.map(billet).find((element) => element.id === params.billetId);
      if (trouve === undefined) {
        return reponseProbleme(404, "TICKET_NOT_FOUND", "Billet introuvable");
      }
      return HttpResponse.json(trouve satisfies Billet);
    }),
  );
}

function rendrePaiement() {
  const clientRequetes = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={clientRequetes}>
      <MemoryRouter initialEntries={[`/commandes/${COMMANDE_ID}/paiement`]}>
        <Routes>
          <Route path="/commandes/:commandeId/paiement" element={<PagePaiement />} />
          <Route path="/commandes/:commandeId" element={<PageCommande />} />
          <Route path="/billets/:billetId" element={<PageBillet />} />
          <Route path="/seances/:seanceId" element={<h1>Plan de salle de test</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  commandeCourante = commande("EN_ATTENTE");
  paiements = [];
});

it.each([
  { expireDansMs: 90_000, affiche: /^01:(29|30)$/ },
  { expireDansMs: 7 * 60_000, affiche: /^0(6:59|7:00)$/ },
])(
  "test_le_compte_a_rebours_suit_l_expiration_renvoyee_par_l_api ($expireDansMs ms)",
  async ({ expireDansMs, affiche }) => {
    commandeCourante = commande("EN_ATTENTE", expireDansMs);
    simulerApi(() => HttpResponse.json<Commande>(commande("CONFIRMEE")));
    rendrePaiement();

    const minuteur = await screen.findByRole("timer");

    expect(minuteur.textContent).toMatch(affiche);
    expect(minuteur).toHaveAccessibleName(/^Temps restant : /);
  },
);

it("test_un_delai_ecoule_retire_le_paiement_et_renvoie_vers_la_seance", async () => {
  commandeCourante = commande("EN_ATTENTE", -1_000);
  simulerApi(() => HttpResponse.json<Commande>(commande("CONFIRMEE")));
  rendrePaiement();

  expect(await screen.findByRole("alert")).toHaveTextContent("Le délai de réservation est écoulé.");
  expect(screen.queryByRole("button", { name: /^Payer/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("timer")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Retour au plan de salle" })).toHaveAttribute(
    "href",
    `/seances/${SEANCE_ID}`,
  );
});

it("test_le_compte_a_rebours_qui_atteint_zero_retire_le_paiement_sans_rechargement", async () => {
  vi.useFakeTimers({
    shouldAdvanceTime: true,
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"],
  });
  try {
    commandeCourante = commande("EN_ATTENTE", 3_000);
    simulerApi(() => HttpResponse.json<Commande>(commande("CONFIRMEE")));
    rendrePaiement();
    expect((await screen.findByRole("timer")).textContent).toMatch(/^00:0[23]$/);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4_000);
    });

    expect(screen.getByRole("alert")).toHaveTextContent("Le délai de réservation est écoulé.");
    expect(screen.queryByRole("timer")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Payer/ })).not.toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});

it("test_un_double_clic_sur_payer_n_envoie_qu_un_seul_paiement", async () => {
  let terminer: () => void = () => {};
  const reponseRetenue = new Promise<void>((resoudre) => {
    terminer = resoudre;
  });
  simulerApi(async () => {
    await reponseRetenue;
    commandeCourante = commande("CONFIRMEE");
    return HttpResponse.json<Commande>(commandeCourante);
  });
  const utilisateur = userEvent.setup();
  rendrePaiement();
  await utilisateur.type(await screen.findByLabelText(/^Numéro de carte/), CARTE_ACCEPTEE);
  const payer = screen.getByRole("button", { name: /^Payer/ });

  // Deux clics dans le même tour, avant tout nouveau rendu.
  fireEvent.click(payer);
  fireEvent.click(payer);
  await waitFor(() => expect(payer).toHaveAttribute("aria-busy", "true"));
  await utilisateur.dblClick(payer);
  terminer();

  expect(await screen.findByText("Paiement accepté.")).toBeInTheDocument();
  expect(paiements).toEqual([{ carte_test: CARTE_ACCEPTEE }]);
});

it("test_apres_paiement_la_confirmation_liste_les_billets_et_chacun_s_affiche_avec_son_qr_code", async () => {
  simulerApi(() => {
    commandeCourante = commande("CONFIRMEE");
    return HttpResponse.json<Commande>(commandeCourante);
  });
  const utilisateur = userEvent.setup();
  rendrePaiement();
  await utilisateur.type(await screen.findByLabelText(/^Numéro de carte/), CARTE_ACCEPTEE);

  await utilisateur.click(screen.getByRole("button", { name: /^Payer/ }));

  expect(
    await screen.findByRole("heading", { level: 1, name: /^Commande du / }),
  ).toBeInTheDocument();
  expect(screen.getByText("Confirmée")).toBeInTheDocument();
  const liens = await screen.findAllByRole("link", { name: /^Voir le billet/ });
  expect(liens).toHaveLength(2);
  await utilisateur.click(screen.getByRole("link", { name: /^Voir le billet\s*Rang B, place 2$/ }));

  expect(
    await screen.findByRole("img", { name: "QR code du billet rang b, place 2" }),
  ).toBeInTheDocument();
  expect(screen.getByText("Valable")).toBeInTheDocument();
});

it("test_un_paiement_refuse_libere_les_places_et_renvoie_vers_la_seance", async () => {
  simulerApi(() => reponseProbleme(402, "PAYMENT_REFUSED", "Paiement refusé"));
  const utilisateur = userEvent.setup();
  rendrePaiement();
  await utilisateur.type(await screen.findByLabelText(/^Numéro de carte/), "4000000000000002");

  await utilisateur.click(screen.getByRole("button", { name: /^Payer/ }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Paiement refusé, vos places sont libérées.",
  );
  expect(screen.queryByRole("button", { name: /^Payer/ })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Retour au plan de salle" })).toBeInTheDocument();
});

it("test_un_numero_de_carte_incomplet_est_signale_sous_le_champ_sans_appel", async () => {
  simulerApi(() => HttpResponse.json<Commande>(commande("CONFIRMEE")));
  const utilisateur = userEvent.setup();
  rendrePaiement();
  const champ = await screen.findByLabelText(/^Numéro de carte/);
  await utilisateur.type(champ, "4242");

  await utilisateur.click(screen.getByRole("button", { name: /^Payer/ }));

  expect(champ).toHaveAttribute("aria-invalid", "true");
  expect(champ).toHaveAccessibleDescription(
    expect.stringContaining("Saisissez les 16 chiffres de votre numéro de carte."),
  );
  expect(paiements).toHaveLength(0);
});
