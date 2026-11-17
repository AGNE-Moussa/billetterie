// Cas composant de BIL-019 (E01) : filtres reflétés dans l'URL (CA1), états vide, page hors
// limites et erreur, bandeau du mode dégradé sur `X-Cache-Stale: true`. API simulée par MSW à
// partir des types générés du contrat Catalogue ; données synthétiques.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";

import type { EvenementPage, Probleme } from "../../api/genere/catalogue";
import { serveurMsw } from "../../mocks/serveur";
import { PageCatalogue } from "./PageCatalogue";

const EVENEMENT = {
  id: "0b6f5a3e-1c2d-4e5f-8a9b-000000000001",
  nom: "Concert de test",
  description: "Description synthétique du concert de test.",
  cree_le: "2026-10-01T10:00:00+02:00",
  prochaine_seance: "2026-12-12T20:00:00+01:00",
  ville: "Lyon",
  prix_min: 2500,
} satisfies EvenementPage["elements"][number];

function page(elements: EvenementPage["elements"], total = elements.length, numero = 1) {
  return { elements, page: numero, size: 20, total } satisfies EvenementPage;
}

function probleme(status: number, code: string, title: string): Probleme {
  return { type: "about:blank", title, status, detail: `Détail de test ${code}.`, code };
}

/** Paramètres de chaque appel à `listerEvenements`, dans l'ordre. */
let appels: URLSearchParams[] = [];

function simulerEvenements(
  repondre: (parametres: URLSearchParams) => Response = () =>
    HttpResponse.json<EvenementPage>(page([EVENEMENT])),
) {
  serveurMsw.use(
    http.get("*/api/v1/events", ({ request }) => {
      const parametres = new URL(request.url).searchParams;
      appels.push(parametres);
      return repondre(parametres);
    }),
  );
}

/** Affiche la partie « recherche » de l'adresse courante. */
function TemoinAdresse() {
  const { search } = useLocation();
  return <p data-testid="adresse">{search}</p>;
}

function parametresAdresse(): URLSearchParams {
  return new URLSearchParams(screen.getByTestId("adresse").textContent ?? "");
}

function rendreA(chemin: string) {
  const clientRequetes = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={clientRequetes}>
      <MemoryRouter initialEntries={[chemin]}>
        <Routes>
          <Route path="/" element={<PageCatalogue />} />
        </Routes>
        <TemoinAdresse />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function resultats() {
  return screen.getByRole("region", { name: "Résultats" });
}

beforeEach(() => {
  appels = [];
});

it("test_chaque_carte_affiche_la_prochaine_seance_la_ville_et_le_prix_d_appel", async () => {
  const SANS_DATE = {
    ...EVENEMENT,
    id: "0b6f5a3e-1c2d-4e5f-8a9b-000000000002",
    nom: "Exposition sans date",
    prochaine_seance: null,
    ville: null,
    prix_min: null,
  };
  simulerEvenements(() => HttpResponse.json<EvenementPage>(page([EVENEMENT, SANS_DATE])));
  rendreA("/");

  const carte = (await screen.findByRole("article", { name: EVENEMENT.nom })) as HTMLElement;
  const apercu = within(carte).getByRole("list", { name: "En bref" });
  expect(within(apercu).getByText("Lyon")).toBeInTheDocument();
  expect(within(apercu).getByText(/^À partir de 25,00\s€$/)).toBeInTheDocument();
  expect(apercu.querySelector("time")).toHaveAttribute("dateTime", EVENEMENT.prochaine_seance);

  const sansDate = screen.getByRole("article", { name: SANS_DATE.nom });
  expect(within(sansDate).getByText("Nouvelles dates bientôt annoncées")).toBeInTheDocument();
  expect(within(sansDate).queryByRole("list", { name: "En bref" })).not.toBeInTheDocument();
});

it("test_filtrer_reporte_les_filtres_dans_l_url_et_les_transmet_a_l_api", async () => {
  simulerEvenements();
  const utilisateur = userEvent.setup();
  rendreA("/");
  await screen.findByRole("heading", { level: 3, name: EVENEMENT.nom });

  await utilisateur.type(screen.getByLabelText("Rechercher"), "jazz");
  await utilisateur.type(screen.getByLabelText("Ville"), "Lyon");
  await utilisateur.click(screen.getByRole("button", { name: "Filtrer" }));

  await waitFor(() => expect(parametresAdresse().get("q")).toBe("jazz"));
  expect(parametresAdresse().get("ville")).toBe("Lyon");
  await waitFor(() => expect(appels.at(-1)?.get("q")).toBe("jazz"));
  const dernier = appels.at(-1);
  expect(dernier?.get("ville")).toBe("Lyon");
});

it("test_un_lien_partage_avec_filtres_preremplit_le_formulaire_et_filtre_la_liste", async () => {
  simulerEvenements();
  rendreA("/?q=jazz&ville=Lyon&du=2026-12-01&au=2026-12-31&page=2");

  await screen.findByRole("heading", { level: 3, name: EVENEMENT.nom });

  expect(screen.getByLabelText("Rechercher")).toHaveValue("jazz");
  expect(screen.getByLabelText("Ville")).toHaveValue("Lyon");
  expect(screen.getByLabelText("Du")).toHaveValue("2026-12-01");
  expect(screen.getByLabelText("Au")).toHaveValue("2026-12-31");
  expect(appels).toHaveLength(1);
  const [appel] = appels;
  expect(appel?.get("q")).toBe("jazz");
  expect(appel?.get("ville")).toBe("Lyon");
  expect(appel?.get("page")).toBe("2");
  // Jours de l'URL convertis en dates-heures ISO (début et fin de journée locale).
  expect(new Date(appel?.get("du") ?? "").getDate()).toBe(1);
  expect(new Date(appel?.get("au") ?? "").getDate()).toBe(31);
});

it("test_aucun_resultat_avec_filtres_propose_d_effacer_les_filtres_et_vide_l_url", async () => {
  simulerEvenements(() => HttpResponse.json<EvenementPage>(page([])));
  const utilisateur = userEvent.setup();
  rendreA("/?q=introuvable");

  expect(
    await within(resultats()).findByText("Aucun événement ne correspond à ces filtres."),
  ).toBeInTheDocument();
  await utilisateur.click(within(resultats()).getByRole("button", { name: "Effacer les filtres" }));

  expect(screen.getByTestId("adresse")).toHaveTextContent(/^$/);
  expect(screen.getByLabelText("Rechercher")).toHaveValue("");
});

it("test_une_page_hors_limites_propose_de_revenir_a_la_premiere_page", async () => {
  simulerEvenements((parametres) =>
    parametres.get("page") === "9"
      ? HttpResponse.json<EvenementPage>(page([], 3, 9))
      : HttpResponse.json<EvenementPage>(page([EVENEMENT], 3)),
  );
  const utilisateur = userEvent.setup();
  rendreA("/?ville=Lyon&page=9");

  expect(await screen.findByText("Cette page n'existe pas.")).toBeInTheDocument();
  await utilisateur.click(screen.getByRole("button", { name: "Revenir à la première page" }));

  expect(await screen.findByRole("heading", { level: 3, name: EVENEMENT.nom })).toBeInTheDocument();
  expect(parametresAdresse().get("page")).toBeNull();
  expect(parametresAdresse().get("ville")).toBe("Lyon");
});

it("test_pendant_le_chargement_la_liste_est_annoncee_et_les_filtres_restent_utilisables", async () => {
  let repondre: () => void = () => {};
  const reponseRetenue = new Promise<void>((resoudre) => {
    repondre = resoudre;
  });
  serveurMsw.use(
    http.get("*/api/v1/events", async () => {
      await reponseRetenue;
      return HttpResponse.json<EvenementPage>(page([EVENEMENT]));
    }),
  );
  const utilisateur = userEvent.setup();
  rendreA("/");

  expect(await screen.findByRole("status")).toHaveTextContent("Chargement des événements…");
  await utilisateur.type(screen.getByLabelText("Ville"), "Lyon");
  expect(screen.getByLabelText("Ville")).toHaveValue("Lyon");
  repondre();

  expect(await screen.findByRole("heading", { level: 3, name: EVENEMENT.nom })).toBeInTheDocument();
});

// Règle commune de docs/front/ecrans.md : bandeau au-dessus du contenu dès que la réponse porte
// X-Cache-Stale, quel que soit l'état affiché (liste, vide, page hors limites).
it("test_une_page_hors_limites_servie_depuis_le_cache_affiche_le_bandeau_du_mode_degrade", async () => {
  simulerEvenements(() =>
    HttpResponse.json<EvenementPage>(page([], 3, 9), { headers: { "X-Cache-Stale": "true" } }),
  );
  rendreA("/?page=9");

  expect(await screen.findByText("Cette page n'existe pas.")).toBeInTheDocument();
  expect(screen.getByText("Données peut-être pas à jour.")).toBeInTheDocument();
});

it("test_une_base_indisponible_affiche_l_erreur_et_reessayer_relit_la_liste", async () => {
  let echec = true;
  simulerEvenements(() =>
    echec
      ? HttpResponse.json<Probleme>(
          probleme(503, "BASE_INDISPONIBLE", "Catalogue momentanément indisponible"),
          { status: 503, headers: { "Content-Type": "application/problem+json" } },
        )
      : HttpResponse.json<EvenementPage>(page([EVENEMENT])),
  );
  const utilisateur = userEvent.setup();
  rendreA("/");

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Catalogue momentanément indisponible",
  );
  echec = false;
  await utilisateur.click(screen.getByRole("button", { name: "Réessayer" }));

  expect(await screen.findByRole("heading", { level: 3, name: EVENEMENT.nom })).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("test_des_filtres_refuses_en_422_s_affichent_sans_bouton_reessayer", async () => {
  simulerEvenements(() =>
    HttpResponse.json<Probleme>(probleme(422, "REQUETE_INVALIDE", "Requête invalide"), {
      status: 422,
      headers: { "Content-Type": "application/problem+json" },
    }),
  );
  rendreA("/?du=2026-12-31&au=2026-12-01");

  expect(await screen.findByRole("alert")).toHaveTextContent("Requête invalide");
  expect(screen.queryByRole("button", { name: "Réessayer" })).not.toBeInTheDocument();
  // Les filtres restent modifiables.
  expect(screen.getByLabelText("Du")).toHaveValue("2026-12-31");
});

it.each<{ cas: string; enTetes: Record<string, string>; bandeau: boolean }>([
  { cas: "X-Cache-Stale: true", enTetes: { "X-Cache-Stale": "true" }, bandeau: true },
  { cas: "sans X-Cache-Stale", enTetes: {}, bandeau: false },
])("test_le_bandeau_du_mode_degrade_suit_l_en_tete_x_cache_stale ($cas)", async (cas) => {
  simulerEvenements(() =>
    HttpResponse.json<EvenementPage>(page([EVENEMENT]), { headers: cas.enTetes }),
  );
  rendreA("/");

  await screen.findByRole("heading", { level: 3, name: EVENEMENT.nom });

  const bandeau = screen.queryByText("Données peut-être pas à jour.");
  if (cas.bandeau) {
    expect(bandeau).toBeInTheDocument();
  } else {
    expect(bandeau).not.toBeInTheDocument();
  }
});
