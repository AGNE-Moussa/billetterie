// Cas composant de BIL-F27 (CA1, CA2, contrainte, E1) : connexion, rappel, déconnexion,
// stockage des jetons et renouvellement silencieux. Deux modes :
// - vrai UserManager configuré comme l'application (parametresOidc), Keycloak simulé par MSW
//   (découverte, point de jeton) ; navigation pleine page et iframe remplacées par des
//   navigateurs de test qui captent les adresses (aucune navigation réelle sous jsdom) ;
// - UserManager injecté, état de session imposé par le test (signinSilent remplacé).
// Jetons JWT synthétiques non signés ; rendu sous MemoryRouter et un QueryClientProvider de test.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import {
  ErrorResponse,
  InMemoryWebStorage,
  User,
  UserManager,
  WebStorageStateStore,
  type INavigator,
  type NavigateResponse,
  type UserProfile,
} from "oidc-client-ts";
import { useEffect } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";

import { listerEchos } from "../api/echos";
import type { EchoPage } from "../api/genere/echo";
import { EnTete } from "../composants/EnTete";
import { serveurMsw } from "../mocks/serveur";
import { PageAccueil } from "../pages/PageAccueil";
import { PageRappelConnexion } from "../pages/PageRappelConnexion";
import { RoutesApplication } from "../RoutesApplication";
import { CHEMIN_RAPPEL, parametresOidc } from "./configurationOidc";
import { FournisseurAuthentification } from "./FournisseurAuthentification";
import { useSession, type Session } from "./session";

const ORIGINE = window.location.origin;
const AUTORITE = `${ORIGINE}/auth/realms/billetterie`;
const POINT_AUTORISATION = `${AUTORITE}/protocol/openid-connect/auth`;
const POINT_JETON = `${AUTORITE}/protocol/openid-connect/token`;
const POINT_FIN_SESSION = `${AUTORITE}/protocol/openid-connect/logout`;
const MESSAGE_GENERIQUE_ATTENDU =
  "Le service est momentanément indisponible. Réessayez dans quelques instants.";
const PAGE_VIDE: EchoPage = { elements: [], page: 1, size: 20, total: 0 };

// ---------------------------------------------------------------------------------------------
// Jetons synthétiques.

function encoderSegment(valeur: unknown): string {
  return btoa(JSON.stringify(valeur)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
}

/** JWT synthétique non signé (le front le décode sans vérifier la signature). */
function jwtDeTest(revendications: Record<string, unknown>): string {
  return `${encoderSegment({ alg: "none", typ: "JWT" })}.${encoderSegment(revendications)}.`;
}

interface JeuDeJetons {
  acces: string;
  rafraichissement: string;
  identite: string;
  profil: UserProfile;
}

function fabriquerJetons(sujet: string, nonce?: string | null): JeuDeJetons {
  const maintenant = Math.floor(Date.now() / 1000);
  const communes = {
    iss: AUTORITE,
    sub: sujet,
    azp: "frontend",
    preferred_username: "client.test",
    iat: maintenant,
    exp: maintenant + 300,
  };
  const profil: UserProfile = { ...communes, aud: "frontend" };
  return {
    acces: jwtDeTest({
      ...communes,
      aud: "billetterie-api",
      jti: `jeton-acces-de-test-${crypto.randomUUID()}`,
      realm_access: { roles: ["customer"] },
    }),
    rafraichissement: `jeton-rafraichissement-de-test-${crypto.randomUUID()}`,
    identite: jwtDeTest({
      ...profil,
      jti: `jeton-identite-de-test-${crypto.randomUUID()}`,
      ...(nonce ? { nonce } : {}),
    }),
    profil,
  };
}

// ---------------------------------------------------------------------------------------------
// Keycloak simulé (realm billetterie) : découverte OIDC, point de jeton, userinfo.

interface RequeteJeton {
  corps: URLSearchParams;
  typeContenu: string | null;
  autorisation: string | null;
}

type ReponseJetonImposee = (
  corps: URLSearchParams,
) => Response | undefined | Promise<Response | undefined>;

function simulerKeycloak() {
  const sujet = crypto.randomUUID();
  const keycloak = {
    requetesJeton: [] as RequeteJeton[],
    emis: [] as JeuDeJetons[],
    /** `nonce` de la demande d'autorisation, repris dans le jeton d'identité s'il existe. */
    nonce: null as string | null,
    /** Réponse imposée au point de jeton ; `undefined` : nouveaux jetons synthétiques. */
    reponseImposee: undefined as ReponseJetonImposee | undefined,
    requetesDeRenouvellement() {
      return keycloak.requetesJeton.filter(
        (requete) => requete.corps.get("grant_type") === "refresh_token",
      );
    },
  };
  serveurMsw.use(
    http.get(`${AUTORITE}/.well-known/openid-configuration`, () =>
      HttpResponse.json({
        issuer: AUTORITE,
        authorization_endpoint: POINT_AUTORISATION,
        token_endpoint: POINT_JETON,
        end_session_endpoint: POINT_FIN_SESSION,
        userinfo_endpoint: `${AUTORITE}/protocol/openid-connect/userinfo`,
        jwks_uri: `${AUTORITE}/protocol/openid-connect/certs`,
        response_types_supported: ["code"],
        code_challenge_methods_supported: ["S256"],
      }),
    ),
    http.get(`${AUTORITE}/protocol/openid-connect/userinfo`, () =>
      HttpResponse.json({ sub: sujet, preferred_username: "client.test" }),
    ),
    http.post(POINT_JETON, async ({ request }) => {
      const corps = new URLSearchParams(await request.text());
      keycloak.requetesJeton.push({
        corps,
        typeContenu: request.headers.get("Content-Type"),
        autorisation: request.headers.get("Authorization"),
      });
      const imposee = await keycloak.reponseImposee?.(corps);
      if (imposee !== undefined) {
        return imposee;
      }
      const jeu = fabriquerJetons(sujet, keycloak.nonce);
      keycloak.emis.push(jeu);
      return HttpResponse.json({
        access_token: jeu.acces,
        refresh_token: jeu.rafraichissement,
        id_token: jeu.identite,
        token_type: "Bearer",
        expires_in: 300,
        scope: "openid profile",
      });
    }),
  );
  return keycloak;
}

function reponseInvalidGrant() {
  return HttpResponse.json(
    { error: "invalid_grant", error_description: "Code not valid" },
    { status: 400 },
  );
}

// ---------------------------------------------------------------------------------------------
// UserManager : celui de l'application (navigateurs de test) ou un UserManager injecté.

/** Navigateur pleine page de test : capte l'adresse au lieu de quitter la page. */
function navigateurQuiCapte(adresses: string[]): INavigator {
  return {
    prepare: () =>
      Promise.resolve({
        navigate: ({ url }) => {
          adresses.push(url);
          return new Promise<NavigateResponse>(() => {});
        },
        close: () => {},
      }),
    callback: () => Promise.resolve(),
  };
}

/** Iframe de test : Keycloak répond `login_required` (aucune session à retrouver). */
const iframeSansSession: INavigator = {
  prepare: () =>
    Promise.resolve({
      navigate: () => Promise.reject(new ErrorResponse({ error: "login_required" })),
      close: () => {},
    }),
  callback: () => Promise.resolve(),
};

function userManagerDeLApplication() {
  const redirections: string[] = [];
  const navigateur = navigateurQuiCapte(redirections);
  const userManager = new UserManager(parametresOidc(), navigateur, navigateur, iframeSansSession);
  return { userManager, redirections };
}

type EtatSession = { connecte: User } | "sans-session";

function utilisateurInjecte(nom: string): User {
  const jeu = fabriquerJetons(crypto.randomUUID());
  const profil: UserProfile = { ...jeu.profil, preferred_username: nom };
  return new User({
    access_token: jeu.acces,
    refresh_token: jeu.rafraichissement,
    id_token: jwtDeTest(profil),
    token_type: "Bearer",
    scope: "openid profile",
    profile: profil,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
  });
}

/** UserManager injecté : la reconnexion silencieuse du démarrage rend l'état demandé. */
function userManagerInjecte(etat: EtatSession) {
  const redirections: string[] = [];
  const navigateur = navigateurQuiCapte(redirections);
  const userManager = new UserManager(
    {
      authority: AUTORITE,
      client_id: "frontend",
      redirect_uri: `${ORIGINE}${CHEMIN_RAPPEL}`,
      userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
      stateStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    },
    navigateur,
    navigateur,
    iframeSansSession,
  );
  const signinSilent = vi.spyOn(userManager, "signinSilent");
  if (etat === "sans-session") {
    signinSilent.mockRejectedValue(new ErrorResponse({ error: "login_required" }));
  } else {
    signinSilent.mockImplementation(async () => {
      await userManager.storeUser(etat.connecte);
      await userManager.events.load(etat.connecte);
      return etat.connecte;
    });
  }
  const signinRedirect = vi.spyOn(userManager, "signinRedirect").mockResolvedValue(undefined);
  return { userManager, signinSilent, signinRedirect, redirections };
}

// ---------------------------------------------------------------------------------------------
// Rendu.

let sessions: Session[] = [];

function TemoinSession() {
  const session = useSession();
  useEffect(() => {
    sessions.push(session);
  }, [session]);
  return null;
}

function TemoinAdresse() {
  const { pathname, search } = useLocation();
  return (
    <p>
      Adresse : {pathname}
      {search}
    </p>
  );
}

function nouveauClientRequetes() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

/** Routes de l'application et une page de test, sous le fournisseur et un MemoryRouter. */
function rendreAvecPageDeTest(userManager: UserManager, chemin: string) {
  return render(
    <QueryClientProvider client={nouveauClientRequetes()}>
      <MemoryRouter initialEntries={[chemin]}>
        <FournisseurAuthentification userManager={userManager}>
          <EnTete />
          <Routes>
            <Route path="/" element={<PageAccueil />} />
            <Route path={CHEMIN_RAPPEL} element={<PageRappelConnexion />} />
            <Route path="/page-de-test" element={<h1>Page de test</h1>} />
          </Routes>
          <TemoinAdresse />
          <TemoinSession />
        </FournisseurAuthentification>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Table des routes de l'application, comme main.tsx (accueil). */
function rendreApplication(userManager: UserManager) {
  return render(
    <QueryClientProvider client={nouveauClientRequetes()}>
      <MemoryRouter initialEntries={["/"]}>
        <FournisseurAuthentification userManager={userManager}>
          <RoutesApplication />
          <TemoinSession />
        </FournisseurAuthentification>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function utilisateurUi() {
  return userEvent.setup({ delay: null });
}

/** Clic sur « Se connecter » depuis `depuis` ; rend l'adresse de redirection captée. */
async function lancerConnexion(
  keycloak: ReturnType<typeof simulerKeycloak>,
  userManager: UserManager,
  redirections: string[],
  depuis: string,
) {
  const vue = rendreAvecPageDeTest(userManager, depuis);
  await utilisateurUi().click(await screen.findByRole("button", { name: "Se connecter" }));
  await waitFor(() => expect(redirections).toHaveLength(1));
  const adresse = new URL(redirections[0] ?? "");
  keycloak.nonce = adresse.searchParams.get("nonce");
  vue.unmount();
  return adresse;
}

/** Retour de Keycloak sur la page de rappel (adresse du routeur et de la fenêtre). */
function revenirSurLeRappel(userManager: UserManager, parametres: string) {
  const chemin = `${CHEMIN_RAPPEL}?${parametres}`;
  window.history.replaceState(null, "", chemin);
  return rendreAvecPageDeTest(userManager, chemin);
}

/** Connexion complète de client.test depuis `depuis`, jusqu'à l'en-tête connecté. */
async function connecterParLeRappel(depuis = "/page-de-test") {
  const keycloak = simulerKeycloak();
  const { userManager, redirections } = userManagerDeLApplication();
  const adresse = await lancerConnexion(keycloak, userManager, redirections, depuis);
  const state = adresse.searchParams.get("state") ?? "";
  revenirSurLeRappel(userManager, `code=${crypto.randomUUID()}&state=${state}`);
  await screen.findByText("client.test");
  return { keycloak, userManager, redirections };
}

function minuteriesSimulees() {
  vi.useFakeTimers({
    shouldAdvanceTime: true,
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"],
  });
}

async function avancerDe(millisecondes: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(millisecondes);
  });
}

function contenuDuStockage(stockage: Storage): string {
  const morceaux: string[] = [];
  for (let indice = 0; indice < stockage.length; indice += 1) {
    const cle = stockage.key(indice) ?? "";
    morceaux.push(cle, stockage.getItem(cle) ?? "");
  }
  return morceaux.join("\n");
}

function clesDuStockage(stockage: Storage): string[] {
  return Array.from({ length: stockage.length }, (_, indice) => stockage.key(indice) ?? "");
}

function attendreAucunJetonDansLeNavigateur(jeux: JeuDeJetons[]) {
  const local = contenuDuStockage(localStorage);
  const session = contenuDuStockage(sessionStorage);
  for (const jeton of jeux.flatMap((jeu) => [jeu.acces, jeu.rafraichissement, jeu.identite])) {
    expect(local).not.toContain(jeton);
    expect(session).not.toContain(jeton);
    expect(document.cookie).not.toContain(jeton);
  }
}

beforeEach(() => {
  sessions = [];
  vi.stubEnv("VITE_KEYCLOAK_URL", undefined);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  window.history.replaceState(null, "", "/");
});

// ---------------------------------------------------------------------------------------------
// CA1 : connexion et déconnexion.

it("test_sans_session_l_en_tete_propose_de_se_connecter", async () => {
  const { userManager } = userManagerInjecte("sans-session");

  rendreApplication(userManager);

  expect(await screen.findByRole("button", { name: "Se connecter" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Se déconnecter" })).not.toBeInTheDocument();
  expect(screen.queryByText("client.test")).not.toBeInTheDocument();
});

it("test_se_connecter_redirige_vers_keycloak_en_code_avec_pkce_s256", async () => {
  simulerKeycloak();
  const { userManager, redirections } = userManagerDeLApplication();
  rendreAvecPageDeTest(userManager, "/");

  await utilisateurUi().click(await screen.findByRole("button", { name: "Se connecter" }));

  await waitFor(() => expect(redirections).toHaveLength(1));
  const adresse = new URL(redirections[0] ?? "");
  expect(`${adresse.origin}${adresse.pathname}`).toBe(POINT_AUTORISATION);
  expect(adresse.searchParams.get("client_id")).toBe("frontend");
  expect(adresse.searchParams.getAll("response_type")).toEqual(["code"]);
  expect(adresse.searchParams.get("code_challenge_method")).toBe("S256");
  expect(adresse.searchParams.get("code_challenge")).toBeTruthy();
  expect(adresse.searchParams.get("state")).toBeTruthy();
  expect(adresse.searchParams.get("redirect_uri")).toBe(`${ORIGINE}/connexion/rappel`);
  expect(redirections).toHaveLength(1);
});

it("test_la_page_de_rappel_annonce_la_connexion_en_cours", async () => {
  const keycloak = simulerKeycloak();
  const { userManager, redirections } = userManagerDeLApplication();
  const adresse = await lancerConnexion(keycloak, userManager, redirections, "/page-de-test");
  let libererJeton = () => {};
  const jetonRetarde = new Promise<undefined>((resoudre) => {
    libererJeton = () => resoudre(undefined);
  });
  keycloak.reponseImposee = () => jetonRetarde;

  revenirSurLeRappel(
    userManager,
    `code=${crypto.randomUUID()}&state=${adresse.searchParams.get("state") ?? ""}`,
  );

  expect(await screen.findByText("Connexion en cours…")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Page de test" })).not.toBeInTheDocument();
  libererJeton();
  // Attendre la fin de l'échange du code : sinon sa requête au point de jeton peut être servie
  // par le Keycloak simulé du test suivant.
  expect(await screen.findByRole("heading", { name: "Page de test" })).toBeInTheDocument();
  expect(keycloak.requetesJeton).toHaveLength(1);
});

it("test_la_page_de_rappel_echange_le_code_et_ramene_a_la_page_demandee", async () => {
  const keycloak = simulerKeycloak();
  const { userManager, redirections } = userManagerDeLApplication();
  const adresse = await lancerConnexion(keycloak, userManager, redirections, "/page-de-test");
  const code = crypto.randomUUID();

  revenirSurLeRappel(userManager, `code=${code}&state=${adresse.searchParams.get("state") ?? ""}`);

  expect(await screen.findByRole("heading", { name: "Page de test" })).toBeInTheDocument();
  expect(screen.getByText("Adresse : /page-de-test")).toBeInTheDocument();
  expect(screen.getByText("client.test")).toBeInTheDocument();
  await waitFor(() => expect(sessions.at(-1)?.statut).toBe("connecte"));
  expect(keycloak.requetesJeton.map((requete) => requete.corps.get("code"))).toEqual([code]);
});

// Review BIL-F27, point 1 : la page de retour est résolue contre l'origine de l'application ;
// une page qui en sortirait ramène à l'accueil, un chemin interne est conservé.
it.each([
  { page: "/\t/evil.example", attendu: "/" },
  { page: "/\\evil.example", attendu: "/" },
  { page: "//evil.example", attendu: "/" },
  { page: "https://evil.example/", attendu: "/" },
  { page: "/.//evil.example", attendu: "/" },
  { page: "/%2e//evil.example", attendu: "/" },
  { page: "/x/..//evil.example", attendu: "/" },
  { page: "/espace?x=1", attendu: "/espace?x=1" },
])(
  "test_une_page_de_retour_hors_de_l_origine_ramene_a_l_accueil ($page -> $attendu)",
  async ({ page, attendu }) => {
    const keycloak = simulerKeycloak();
    const { userManager, redirections } = userManagerDeLApplication();
    const vue = rendreAvecPageDeTest(userManager, "/");
    await waitFor(() => expect(sessions.at(-1)?.statut).toBe("non-connecte"));

    // seConnecter est public : la page de retour est fournie telle quelle par l'appelant.
    void sessions.at(-1)?.seConnecter(page);
    await waitFor(() => expect(redirections).toHaveLength(1));
    const adresse = new URL(redirections[0] ?? "");
    keycloak.nonce = adresse.searchParams.get("nonce");
    vue.unmount();
    revenirSurLeRappel(
      userManager,
      `code=${crypto.randomUUID()}&state=${adresse.searchParams.get("state") ?? ""}`,
    );
    await screen.findByText("client.test");
    const temoin = await screen.findByText(/^Adresse :/);

    // textContent brut : la tabulation n'est pas normalisée comme dans getByText.
    await waitFor(() => expect(temoin.textContent).toBe(`Adresse : ${attendu}`));
  },
);

it.each([
  { cas: "?error=access_denied", erreurKeycloak: true },
  { cas: "point de jeton 400 invalid_grant", erreurKeycloak: false },
])("test_un_rappel_en_erreur_affiche_le_message_generique ($cas)", async ({ erreurKeycloak }) => {
  const keycloak = simulerKeycloak();
  keycloak.reponseImposee = () => reponseInvalidGrant();
  const { userManager, redirections } = userManagerDeLApplication();
  const adresse = await lancerConnexion(keycloak, userManager, redirections, "/page-de-test");
  const state = adresse.searchParams.get("state") ?? "";

  revenirSurLeRappel(
    userManager,
    erreurKeycloak
      ? `error=access_denied&state=${state}`
      : `code=${crypto.randomUUID()}&state=${state}`,
  );

  expect(await screen.findByText(MESSAGE_GENERIQUE_ATTENDU)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Se connecter" })).toBeInTheDocument();
  await waitFor(() => expect(sessions.at(-1)?.statut).toBe("non-connecte"));
  await waitFor(() => expect(sessions.at(-1)?.utilisateur).toBeNull());
});

it("test_connecte_l_en_tete_affiche_le_nom_d_utilisateur_et_propose_de_se_deconnecter", async () => {
  const { userManager } = userManagerInjecte({ connecte: utilisateurInjecte("client.test") });

  rendreApplication(userManager);

  expect(await screen.findByText("client.test")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Se déconnecter" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Se connecter" })).not.toBeInTheDocument();
});

it("test_se_deconnecter_oublie_l_utilisateur_et_ferme_la_session_keycloak", async () => {
  const { keycloak, userManager, redirections } = await connecterParLeRappel();
  const jetonIdentite = keycloak.emis.at(-1)?.identite;

  await utilisateurUi().click(screen.getByRole("button", { name: "Se déconnecter" }));

  await waitFor(() => expect(redirections).toHaveLength(2));
  const adresse = new URL(redirections[1] ?? "");
  expect(`${adresse.origin}${adresse.pathname}`).toBe(POINT_FIN_SESSION);
  expect(adresse.searchParams.get("id_token_hint")).toBe(jetonIdentite);
  expect(adresse.searchParams.get("post_logout_redirect_uri")).toBe(`${ORIGINE}/`);
  await waitFor(() => expect(sessions.at(-1)?.utilisateur).toBeNull());
  expect(await userManager.getUser()).toBeNull();
});

// ---------------------------------------------------------------------------------------------
// CA2 : aucun jeton dans localStorage ni sessionStorage.

it("test_apres_connexion_aucun_jeton_n_est_dans_le_stockage_du_navigateur", async () => {
  const { keycloak } = await connecterParLeRappel();
  const captees: (string | null)[] = [];
  serveurMsw.use(
    http.get("*/api/v1/echos", ({ request }) => {
      captees.push(request.headers.get("Authorization"));
      return HttpResponse.json<EchoPage>(PAGE_VIDE);
    }),
  );

  expect(keycloak.emis).toHaveLength(1);
  attendreAucunJetonDansLeNavigateur(keycloak.emis);
  await expect(listerEchos()).resolves.toEqual(PAGE_VIDE);
  expect(captees).toEqual([`Bearer ${keycloak.emis[0]?.acces}`]);
});

it("test_l_etat_temporaire_de_connexion_va_en_session_storage_jamais_en_local_storage", async () => {
  simulerKeycloak();
  const { userManager, redirections } = userManagerDeLApplication();
  rendreAvecPageDeTest(userManager, "/");

  await utilisateurUi().click(await screen.findByRole("button", { name: "Se connecter" }));

  await waitFor(() => expect(redirections).toHaveLength(1));
  const state = new URL(redirections[0] ?? "").searchParams.get("state") ?? "";
  expect(state).not.toBe("");
  const cleEtat = clesDuStockage(sessionStorage).find((cle) => cle.endsWith(state));
  expect(cleEtat).toBeDefined();
  const etat: unknown = JSON.parse(sessionStorage.getItem(cleEtat ?? "") ?? "null");
  expect(etat).toMatchObject({ id: state, code_verifier: expect.any(String) });
  expect(clesDuStockage(localStorage).filter((cle) => cle.startsWith("oidc."))).toEqual([]);
  expect(contenuDuStockage(localStorage)).not.toContain(state);
  for (const nom of ["access_token", "refresh_token", "id_token"]) {
    expect(contenuDuStockage(localStorage)).not.toContain(nom);
    expect(contenuDuStockage(sessionStorage)).not.toContain(nom);
  }
});

it("test_apres_renouvellement_aucun_jeton_n_est_dans_le_stockage_du_navigateur", async () => {
  minuteriesSimulees();
  const { keycloak } = await connecterParLeRappel();

  await avancerDe(250_000);

  await waitFor(() => expect(keycloak.emis).toHaveLength(2));
  await waitFor(() =>
    expect(sessions.at(-1)?.utilisateur?.access_token).toBe(keycloak.emis[1]?.acces),
  );
  attendreAucunJetonDansLeNavigateur(keycloak.emis);
});

// ---------------------------------------------------------------------------------------------
// Contrainte : client public, aucun secret.

it.each([
  { etape: "échange du code", grant: "authorization_code" },
  { etape: "renouvellement par jeton de rafraîchissement", grant: "refresh_token" },
])(
  "test_les_requetes_au_point_de_jeton_n_envoient_aucun_secret_client ($etape)",
  async ({ grant }) => {
    const { keycloak, userManager } = await connecterParLeRappel();
    if (grant === "refresh_token") {
      await act(async () => {
        await userManager.signinSilent();
      });
    }

    const requete = keycloak.requetesJeton.find((r) => r.corps.get("grant_type") === grant);
    expect(requete).toBeDefined();
    expect(requete?.typeContenu).toContain("application/x-www-form-urlencoded");
    expect(requete?.corps.get("client_id")).toBe("frontend");
    if (grant === "authorization_code") {
      const verificateur = requete?.corps.get("code_verifier") ?? "";
      expect(verificateur.length).toBeGreaterThanOrEqual(43);
      expect(verificateur.length).toBeLessThanOrEqual(128);
    } else {
      expect(requete?.corps.get("refresh_token")).toBe(keycloak.emis[0]?.rafraichissement);
    }
    expect(requete?.corps.has("client_secret")).toBe(false);
    expect(requete?.autorisation).toBeNull();
  },
);

// ---------------------------------------------------------------------------------------------
// E1 : renouvellement silencieux.

it("test_le_jeton_est_renouvele_par_jeton_de_rafraichissement_60_s_avant_son_expiration", async () => {
  minuteriesSimulees();
  const { keycloak, redirections } = await connecterParLeRappel();
  const premier = keycloak.emis[0];

  // Jeton d'accès émis pour 300 s : rien avant 240 s.
  await avancerDe(235_000);
  expect(keycloak.requetesDeRenouvellement()).toHaveLength(0);

  await avancerDe(15_000);
  await waitFor(() => expect(keycloak.requetesDeRenouvellement()).toHaveLength(1));
  expect(keycloak.requetesDeRenouvellement()[0]?.corps.get("refresh_token")).toBe(
    premier?.rafraichissement,
  );
  await waitFor(() =>
    expect(sessions.at(-1)?.utilisateur?.access_token).toBe(keycloak.emis[1]?.acces),
  );
  expect(sessions.at(-1)?.statut).toBe("connecte");
  expect(screen.getByText("client.test")).toBeInTheDocument();
  expect(redirections).toHaveLength(1);
});

it("test_un_echec_du_renouvellement_ramene_a_l_etat_non_connecte_avec_session_expiree", async () => {
  minuteriesSimulees();
  const { keycloak } = await connecterParLeRappel();
  keycloak.reponseImposee = (corps) =>
    corps.get("grant_type") === "refresh_token" ? reponseInvalidGrant() : undefined;

  await avancerDe(250_000);

  expect(await screen.findByText(/Votre session a expiré/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Se connecter" })).toBeInTheDocument();
  expect(screen.queryByText("client.test")).not.toBeInTheDocument();
  await waitFor(() => expect(sessions.at(-1)?.utilisateur).toBeNull());
  expect(keycloak.requetesDeRenouvellement()).toHaveLength(1);
});

it("test_au_demarrage_la_session_keycloak_existante_est_retrouvee_sans_saisie", async () => {
  const { userManager, signinSilent, signinRedirect, redirections } = userManagerInjecte({
    connecte: utilisateurInjecte("client.test"),
  });

  rendreApplication(userManager);

  expect(await screen.findByText("client.test")).toBeInTheDocument();
  expect(signinSilent).toHaveBeenCalledTimes(1);
  expect(signinRedirect).not.toHaveBeenCalled();
  expect(redirections).toEqual([]);
});

it("test_au_demarrage_sans_session_keycloak_l_application_reste_non_connectee", async () => {
  const { userManager, signinSilent, signinRedirect, redirections } =
    userManagerInjecte("sans-session");

  rendreApplication(userManager);

  expect(await screen.findByRole("button", { name: "Se connecter" })).toBeInTheDocument();
  expect(signinSilent).toHaveBeenCalled();
  await waitFor(() => expect(sessions.at(-1)?.statut).toBe("non-connecte"));
  expect(signinRedirect).not.toHaveBeenCalled();
  expect(redirections).toEqual([]);
});
