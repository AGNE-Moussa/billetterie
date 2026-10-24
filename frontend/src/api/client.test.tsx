// Cas composant de BIL-F27 (E3) : client typé unique (openapi-fetch, types de genere/echo.ts),
// jeton d'accès en Bearer, X-Correlation-Id UUID v4 par requête, renouvellement puis un seul
// rejeu sur 401. API et Keycloak simulés par MSW ; jetons JWT synthétiques non signés.
// Deux modes : source de jeton branchée par le test (intercepteur seul) ; fournisseur
// d'authentification avec un vrai UserManager configuré comme l'application (parametresOidc),
// navigation et iframe remplacées par des navigateurs de test.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import {
  ErrorResponse,
  User,
  UserManager,
  type INavigator,
  type NavigateResponse,
  type UserProfile,
} from "oidc-client-ts";
import { useEffect } from "react";
import { MemoryRouter } from "react-router";

import { parametresOidc } from "../auth/configurationOidc";
import { FournisseurAuthentification } from "../auth/FournisseurAuthentification";
import { useSession, type Session } from "../auth/session";
import { EnTete } from "../composants/EnTete";
import { serveurMsw } from "../mocks/serveur";
import { brancherSourceJeton, clientApi, type SourceJeton } from "./client";
import { listerEchos } from "./echos";
import type { EchoPage, EchoReponse, Probleme } from "./genere/echo";
import { ErreurApi } from "./problemes";

const ORIGINE = window.location.origin;
const AUTORITE = `${ORIGINE}/auth/realms/billetterie`;
const POINT_JETON = `${AUTORITE}/protocol/openid-connect/token`;
const FORMAT_UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

const ECHO_BONJOUR: EchoReponse = {
  message: "bonjour",
  instance: "echo-test-1",
  cree_le: "2026-10-23T10:00:00+02:00",
};
const PAGE_ECHOS: EchoPage = {
  elements: [
    ECHO_BONJOUR,
    { message: "salut", instance: "echo-test-2", cree_le: "2026-10-23T10:05:00+02:00" },
  ],
  page: 1,
  size: 20,
  total: 2,
};

// ---------------------------------------------------------------------------------------------
// Journal des requêtes simulées (API et point de jeton), dans l'ordre d'arrivée.

interface RequeteApi {
  type: "api";
  url: string;
  autorisation: string | null;
  correlation: string | null;
  enTetes: [string, string][];
}
interface RequeteJeton {
  type: "jeton";
  grant: string | null;
}
let journal: (RequeteApi | RequeteJeton)[] = [];

function noterRequeteApi(request: Request): RequeteApi {
  const requete: RequeteApi = {
    type: "api",
    url: request.url,
    autorisation: request.headers.get("Authorization"),
    correlation: request.headers.get("X-Correlation-Id"),
    enTetes: [...request.headers.entries()],
  };
  journal.push(requete);
  return requete;
}

function requetesApi(): RequeteApi[] {
  return journal.filter((requete): requete is RequeteApi => requete.type === "api");
}

/** Le journal à partir de la première requête vers l'API (ignore le démarrage). */
function depuisLaPremiereRequeteApi() {
  return journal.slice(journal.findIndex((requete) => requete.type === "api"));
}

function reponseJetonExpire() {
  return HttpResponse.json<Probleme>(
    {
      type: "about:blank",
      title: "Unauthorized",
      status: 401,
      detail: "Le jeton de test a expiré.",
      code: "JETON_EXPIRE",
    },
    { status: 401, headers: { "Content-Type": "application/problem+json" } },
  );
}

// ---------------------------------------------------------------------------------------------
// Jetons et Keycloak simulés.

function encoderSegment(valeur: unknown): string {
  return btoa(JSON.stringify(valeur)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
}

function jwtDeTest(revendications: Record<string, unknown>): string {
  return `${encoderSegment({ alg: "none", typ: "JWT" })}.${encoderSegment(revendications)}.`;
}

interface JeuDeJetons {
  acces: string;
  rafraichissement: string;
  identite: string;
  profil: UserProfile;
}

function fabriquerJetons(sujet: string): JeuDeJetons {
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
    identite: jwtDeTest({ ...profil, jti: `jeton-identite-de-test-${crypto.randomUUID()}` }),
    profil,
  };
}

function utilisateurDe(jeu: JeuDeJetons): User {
  return new User({
    access_token: jeu.acces,
    refresh_token: jeu.rafraichissement,
    id_token: jeu.identite,
    token_type: "Bearer",
    scope: "openid profile",
    profile: jeu.profil,
    expires_at: Math.floor(Date.now() / 1000) + 300,
  });
}

/** Découverte OIDC, point de jeton et userinfo du realm billetterie simulés. */
function simulerKeycloak(options: { echecRenouvellement?: () => boolean } = {}) {
  const sujet = crypto.randomUUID();
  const initial = fabriquerJetons(sujet);
  const emis: JeuDeJetons[] = [];
  serveurMsw.use(
    http.get(`${AUTORITE}/.well-known/openid-configuration`, () =>
      HttpResponse.json({
        issuer: AUTORITE,
        authorization_endpoint: `${AUTORITE}/protocol/openid-connect/auth`,
        token_endpoint: POINT_JETON,
        end_session_endpoint: `${AUTORITE}/protocol/openid-connect/logout`,
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
      journal.push({ type: "jeton", grant: corps.get("grant_type") });
      if (corps.get("grant_type") === "refresh_token" && options.echecRenouvellement?.()) {
        return HttpResponse.json(
          { error: "invalid_grant", error_description: "Token is not active" },
          { status: 400 },
        );
      }
      const jeu = fabriquerJetons(sujet);
      emis.push(jeu);
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
  return { initial, emis };
}

/** Vrai UserManager configuré comme l'application ; navigation pleine page et iframe captées. */
function userManagerDeLApplication() {
  const redirections: string[] = [];
  const navigateurRedirection: INavigator = {
    prepare: () =>
      Promise.resolve({
        navigate: ({ url }) => {
          redirections.push(url);
          return new Promise<NavigateResponse>(() => {});
        },
        close: () => {},
      }),
    callback: () => Promise.resolve(),
  };
  const navigateurSilencieux: INavigator = {
    prepare: () =>
      Promise.resolve({
        navigate: () => Promise.reject(new ErrorResponse({ error: "login_required" })),
        close: () => {},
      }),
    callback: () => Promise.resolve(),
  };
  const userManager = new UserManager(
    parametresOidc(),
    navigateurRedirection,
    navigateurRedirection,
    navigateurSilencieux,
  );
  return { userManager, redirections };
}

let sessions: Session[] = [];

function TemoinSession() {
  const session = useSession();
  useEffect(() => {
    sessions.push(session);
  }, [session]);
  return <p>Statut : {session.statut}</p>;
}

/** Fournisseur avec l'utilisateur en mémoire du UserManager ; attend l'état connecté. */
async function connecter(userManager: UserManager, utilisateur: User) {
  await userManager.storeUser(utilisateur);
  const clientRequetes = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={clientRequetes}>
      <MemoryRouter>
        <FournisseurAuthentification userManager={userManager}>
          <EnTete />
          <TemoinSession />
        </FournisseurAuthentification>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText("Statut : connecte");
}

// ---------------------------------------------------------------------------------------------
// Source de jeton branchée par le test (débranchée après chaque test qui l'a branchée).

let sourceBranchee = false;

function brancher(source: SourceJeton | null) {
  brancherSourceJeton(source);
  sourceBranchee = true;
}

function sourceDeTest(jeton: string): SourceJeton {
  return { jetonAcces: () => jeton, renouveler: () => Promise.resolve(null) };
}

function simulerListeEchos() {
  serveurMsw.use(
    http.get("*/api/v1/echos", ({ request }) => {
      noterRequeteApi(request);
      return HttpResponse.json<EchoPage>(PAGE_ECHOS);
    }),
  );
}

function simulerLectureEcho() {
  serveurMsw.use(
    http.get("*/api/v1/echos/:message", ({ request }) => {
      noterRequeteApi(request);
      return HttpResponse.json<EchoReponse>(ECHO_BONJOUR);
    }),
  );
}

beforeEach(() => {
  journal = [];
  sessions = [];
});

afterEach(() => {
  if (sourceBranchee) {
    brancherSourceJeton(null);
    sourceBranchee = false;
  }
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------------------------

it("test_lister_echos_rend_la_page_typee_du_contrat", async () => {
  simulerListeEchos();

  await expect(listerEchos({ page: 1, size: 20 })).resolves.toEqual(PAGE_ECHOS);

  expect(requetesApi().map((requete) => requete.url)).toEqual([
    `${ORIGINE}/api/v1/echos?page=1&size=20`,
  ]);
});

it("test_le_client_ajoute_le_jeton_d_acces_en_bearer", async () => {
  const jeton = `jeton-acces-de-test-${crypto.randomUUID()}`;
  brancher(sourceDeTest(jeton));
  simulerLectureEcho();

  const { data } = await clientApi().GET("/api/v1/echos/{message}", {
    params: { path: { message: "bonjour" } },
  });

  expect(data).toEqual(ECHO_BONJOUR);
  expect(requetesApi().map((requete) => requete.autorisation)).toEqual([`Bearer ${jeton}`]);
});

it("test_le_client_ajoute_un_x_correlation_id_uuid_v4", async () => {
  brancher(sourceDeTest(`jeton-acces-de-test-${crypto.randomUUID()}`));
  simulerLectureEcho();

  await clientApi().GET("/api/v1/echos/{message}", { params: { path: { message: "bonjour" } } });

  expect(requetesApi()).toHaveLength(1);
  expect(requetesApi()[0]?.correlation).toMatch(FORMAT_UUID_V4);
});

it("test_deux_requetes_portent_des_x_correlation_id_differents", async () => {
  simulerListeEchos();

  await expect(listerEchos()).resolves.toEqual(PAGE_ECHOS);
  await expect(listerEchos()).resolves.toEqual(PAGE_ECHOS);

  const correlations = requetesApi().map((requete) => requete.correlation);
  expect(correlations).toHaveLength(2);
  expect(correlations[0]).toMatch(FORMAT_UUID_V4);
  expect(correlations[1]).toMatch(FORMAT_UUID_V4);
  expect(correlations[0]).not.toBe(correlations[1]);
});

it.each([
  {
    cas: "VITE_API_URL absente",
    valeur: undefined,
    attendue: `${ORIGINE}/api/v1/echos?page=1&size=20`,
  },
  {
    cas: "VITE_API_URL = http://api.exemple.test/api",
    valeur: "http://api.exemple.test/api",
    attendue: "http://api.exemple.test/api/v1/echos?page=1&size=20",
  },
])(
  "test_le_client_appelle_le_chemin_du_contrat_sur_l_origine_de_l_url_d_api ($cas)",
  async ({ valeur, attendue }) => {
    vi.stubEnv("VITE_API_URL", valeur);
    simulerListeEchos();

    await expect(listerEchos({ page: 1, size: 20 })).resolves.toEqual(PAGE_ECHOS);

    expect(requetesApi().map((requete) => requete.url)).toEqual([attendue]);
    expect(requetesApi()[0]?.url).not.toContain("/api/api/");
  },
);

it("test_sans_session_la_requete_part_sans_en_tete_authorization", async () => {
  brancher(null);
  simulerListeEchos();

  await expect(listerEchos()).resolves.toEqual(PAGE_ECHOS);

  expect(requetesApi()).toHaveLength(1);
  expect(requetesApi()[0]?.correlation).toMatch(FORMAT_UUID_V4);
  expect(requetesApi()[0]?.autorisation).toBeNull();
});

it("test_apres_renouvellement_le_client_envoie_le_nouveau_jeton", async () => {
  vi.useFakeTimers({
    shouldAdvanceTime: true,
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"],
  });
  const keycloak = simulerKeycloak();
  const { userManager } = userManagerDeLApplication();
  await connecter(userManager, utilisateurDe(keycloak.initial));
  const emisAvant = keycloak.emis.length;

  // Expiration à 300 s : le renouvellement est attendu 60 s avant.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(250_000);
  });
  await waitFor(() => expect(keycloak.emis.length).toBeGreaterThan(emisAvant));
  const nouveau = keycloak.emis.at(-1);
  await waitFor(() => expect(sessions.at(-1)?.utilisateur?.access_token).toBe(nouveau?.acces));
  simulerListeEchos();
  await expect(listerEchos()).resolves.toEqual(PAGE_ECHOS);

  const autorisation = requetesApi().at(-1)?.autorisation;
  expect(autorisation).toBe(`Bearer ${nouveau?.acces}`);
  expect(autorisation).not.toContain(keycloak.initial.acces);
});

it("test_apres_deconnexion_le_client_n_envoie_plus_l_ancien_jeton", async () => {
  const keycloak = simulerKeycloak();
  const { userManager, redirections } = userManagerDeLApplication();
  await connecter(userManager, utilisateurDe(keycloak.initial));

  await userEvent
    .setup({ delay: null })
    .click(screen.getByRole("button", { name: "Se déconnecter" }));
  await waitFor(() => expect(redirections).toHaveLength(1));
  await screen.findByText("Statut : non-connecte");
  simulerListeEchos();
  await expect(listerEchos()).resolves.toEqual(PAGE_ECHOS);

  const requete = requetesApi().at(-1);
  expect(requete?.autorisation).toBeNull();
  const anciensJetons = [keycloak.initial, ...keycloak.emis].map((jeu) => jeu.acces);
  for (const [, valeur] of requete?.enTetes ?? []) {
    for (const ancien of anciensJetons) {
      expect(valeur).not.toContain(ancien);
    }
  }
});

it("test_une_reponse_401_declenche_un_renouvellement_puis_un_seul_rejeu", async () => {
  const keycloak = simulerKeycloak();
  const { userManager } = userManagerDeLApplication();
  await connecter(userManager, utilisateurDe(keycloak.initial));
  let appels = 0;
  serveurMsw.use(
    http.get("*/api/v1/echos", ({ request }): Response => {
      noterRequeteApi(request);
      appels += 1;
      return appels === 1 ? reponseJetonExpire() : HttpResponse.json<EchoPage>(PAGE_ECHOS);
    }),
  );

  await expect(listerEchos()).resolves.toEqual(PAGE_ECHOS);

  const suite = depuisLaPremiereRequeteApi();
  expect(suite.map((requete) => requete.type)).toEqual(["api", "jeton", "api"]);
  const [premiere, , seconde] = suite;
  expect((seconde as RequeteApi).autorisation).toBe(`Bearer ${keycloak.emis.at(-1)?.acces}`);
  expect((premiere as RequeteApi).autorisation).not.toBe((seconde as RequeteApi).autorisation);
});

it("test_un_401_apres_le_rejeu_rend_l_erreur_sans_autre_tentative", async () => {
  const keycloak = simulerKeycloak();
  const { userManager } = userManagerDeLApplication();
  await connecter(userManager, utilisateurDe(keycloak.initial));
  serveurMsw.use(
    http.get("*/api/v1/echos", ({ request }) => {
      noterRequeteApi(request);
      return reponseJetonExpire();
    }),
  );

  await expect(listerEchos()).rejects.toMatchObject({ probleme: { code: "JETON_EXPIRE" } });

  expect(depuisLaPremiereRequeteApi().map((requete) => requete.type)).toEqual([
    "api",
    "jeton",
    "api",
  ]);
});

it("test_un_echec_du_renouvellement_apres_401_rend_l_erreur_sans_rejeu", async () => {
  const keycloak = simulerKeycloak({
    echecRenouvellement: () => journal.some((requete) => requete.type === "api"),
  });
  const { userManager } = userManagerDeLApplication();
  await connecter(userManager, utilisateurDe(keycloak.initial));
  serveurMsw.use(
    http.get("*/api/v1/echos", ({ request }) => {
      noterRequeteApi(request);
      return reponseJetonExpire();
    }),
  );

  await expect(listerEchos()).rejects.toBeInstanceOf(ErreurApi);

  expect(depuisLaPremiereRequeteApi().map((requete) => requete.type)).toEqual(["api", "jeton"]);
  expect(await screen.findByText(/Votre session a expiré/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Se connecter" })).toBeInTheDocument();
  expect(screen.getByText("Statut : non-connecte")).toBeInTheDocument();
});

function texteJournalise(argument: unknown): string {
  if (typeof argument === "string") {
    return argument;
  }
  if (argument instanceof Error) {
    return `${argument.name} ${argument.message} ${argument.stack ?? ""}`;
  }
  try {
    return JSON.stringify(argument) ?? String(argument);
  } catch {
    return String(argument);
  }
}

it("test_aucun_jeton_n_apparait_dans_la_console", async () => {
  const espions = (["log", "info", "warn", "error", "debug"] as const).map((methode) =>
    vi.spyOn(console, methode).mockImplementation(() => {}),
  );
  let scenario: "succes" | "rejeu" | "echec" = "succes";
  let appelsDuScenario = 0;
  const keycloak = simulerKeycloak({ echecRenouvellement: () => scenario === "echec" });
  const { userManager } = userManagerDeLApplication();
  await connecter(userManager, utilisateurDe(keycloak.initial));
  serveurMsw.use(
    http.get("*/api/v1/echos", ({ request }): Response => {
      noterRequeteApi(request);
      appelsDuScenario += 1;
      if (scenario === "echec" || (scenario === "rejeu" && appelsDuScenario === 1)) {
        return reponseJetonExpire();
      }
      return HttpResponse.json<EchoPage>(PAGE_ECHOS);
    }),
  );

  await expect(listerEchos()).resolves.toEqual(PAGE_ECHOS);
  scenario = "rejeu";
  appelsDuScenario = 0;
  await expect(listerEchos()).resolves.toEqual(PAGE_ECHOS);
  scenario = "echec";
  appelsDuScenario = 0;
  await expect(listerEchos()).rejects.toBeInstanceOf(ErreurApi);
  expect(await screen.findByText("Statut : non-connecte")).toBeInTheDocument();

  const jetons = [keycloak.initial, ...keycloak.emis].flatMap((jeu) => [
    jeu.acces,
    jeu.rafraichissement,
    jeu.identite,
  ]);
  const journalise = espions
    .flatMap((espion) => espion.mock.calls.flat())
    .map((argument) => texteJournalise(argument));
  for (const texte of journalise) {
    for (const jeton of jetons) {
      expect(texte).not.toContain(jeton);
    }
  }
});
