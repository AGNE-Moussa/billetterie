// Cas composant de BIL-F27 (E2) : gardes de routes par rôle. Routes protégées déclarées par le
// test sous MemoryRouter ; UserManager injecté dans le fournisseur, état de session imposé par
// le test (signinSilent remplacé) ; jetons JWT synthétiques non signés.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
import { MemoryRouter, Route, Routes } from "react-router";

import { MESSAGE_GENERIQUE } from "../api/problemes";
import { CHEMIN_RAPPEL } from "./configurationOidc";
import { FournisseurAuthentification } from "./FournisseurAuthentification";
import { GardeRoles } from "./GardeRoles";
import type { Role } from "./roles";

const ORIGINE = window.location.origin;
const AUTORITE = `${ORIGINE}/auth/realms/billetterie`;
const CONTENU_PROTEGE = "Contenu protégé de test";

function encoderSegment(valeur: unknown): string {
  return btoa(JSON.stringify(valeur)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
}

/** JWT synthétique non signé (le front le décode sans vérifier la signature). */
function jwtDeTest(revendications: Record<string, unknown>): string {
  return `${encoderSegment({ alg: "none", typ: "JWT" })}.${encoderSegment(revendications)}.`;
}

interface OptionsUtilisateur {
  /** `realm_access.roles` du jeton d'accès ; `undefined` : pas de `realm_access`. */
  roles: readonly string[] | undefined;
  /** `realm_access.roles` porté par le profil d'identité (absent par défaut). */
  rolesIdentite?: readonly string[];
  nom?: string;
}

function utilisateurDeTest({ roles, rolesIdentite, nom = "client.test" }: OptionsUtilisateur) {
  const maintenant = Math.floor(Date.now() / 1000);
  const communes = {
    iss: AUTORITE,
    sub: crypto.randomUUID(),
    azp: "frontend",
    preferred_username: nom,
    iat: maintenant,
    exp: maintenant + 3600,
  };
  const jetonAcces = jwtDeTest({
    ...communes,
    aud: "billetterie-api",
    jti: `jeton-acces-de-test-${crypto.randomUUID()}`,
    ...(roles === undefined ? {} : { realm_access: { roles } }),
  });
  const profil: UserProfile = {
    ...communes,
    aud: "frontend",
    ...(rolesIdentite === undefined ? {} : { realm_access: { roles: rolesIdentite } }),
  };
  return new User({
    access_token: jetonAcces,
    id_token: jwtDeTest(profil),
    refresh_token: `jeton-rafraichissement-de-test-${crypto.randomUUID()}`,
    token_type: "Bearer",
    scope: "openid profile",
    profile: profil,
    expires_at: maintenant + 3600,
  });
}

/** Navigateur qui n'ouvre rien (aucune navigation réelle dans jsdom). */
const navigateurSansEffet: INavigator = {
  prepare: () =>
    Promise.resolve({
      navigate: () => new Promise<NavigateResponse>(() => {}),
      close: () => {},
    }),
  callback: () => Promise.resolve(),
};

type EtatSession = { connecte: User } | "sans-session" | "chargement";

/** UserManager injecté ; la reconnexion silencieuse du démarrage rend l'état demandé. */
function userManagerDeTest(etat: EtatSession) {
  const userManager = new UserManager(
    {
      authority: AUTORITE,
      client_id: "frontend",
      redirect_uri: `${ORIGINE}${CHEMIN_RAPPEL}`,
      userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
      stateStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    },
    navigateurSansEffet,
    navigateurSansEffet,
    navigateurSansEffet,
  );
  const signinSilent = vi.spyOn(userManager, "signinSilent");
  if (etat === "chargement") {
    signinSilent.mockReturnValue(new Promise<User | null>(() => {}));
  } else if (etat === "sans-session") {
    signinSilent.mockRejectedValue(new ErrorResponse({ error: "login_required" }));
  } else {
    signinSilent.mockImplementation(async () => {
      await userManager.storeUser(etat.connecte);
      await userManager.events.load(etat.connecte);
      return etat.connecte;
    });
  }
  const signinRedirect = vi.spyOn(userManager, "signinRedirect").mockResolvedValue(undefined);
  return { userManager, signinRedirect };
}

function rendreRouteGardee(userManager: UserManager, roles: readonly Role[]) {
  const clientRequetes = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={clientRequetes}>
      <MemoryRouter initialEntries={["/page-protegee"]}>
        <FournisseurAuthentification userManager={userManager}>
          <Routes>
            <Route path="/" element={<h1>Accueil de test</h1>} />
            <Route
              path="/page-protegee"
              element={
                <GardeRoles roles={roles}>
                  <p>{CONTENU_PROTEGE}</p>
                </GardeRoles>
              }
            />
          </Routes>
        </FournisseurAuthentification>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function attendreAccesRefuse() {
  return screen.findByRole("heading", { level: 1, name: "Accès refusé" });
}

afterEach(() => {
  vi.restoreAllMocks();
});

it("test_une_route_protegee_sans_session_redirige_vers_keycloak_avec_retour_a_la_page_demandee", async () => {
  const { userManager, signinRedirect } = userManagerDeTest("sans-session");

  rendreRouteGardee(userManager, ["customer"]);

  await waitFor(() => expect(signinRedirect).toHaveBeenCalledTimes(1));
  expect(JSON.stringify(signinRedirect.mock.calls[0])).toContain("/page-protegee");
  expect(screen.queryByText(CONTENU_PROTEGE)).not.toBeInTheDocument();
});

// Review BIL-F27, suggestion GardeRoles.tsx:23 : état erreur d'une route gardée.
it("test_un_echec_de_la_redirection_vers_keycloak_affiche_le_message_generique", async () => {
  const { userManager, signinRedirect } = userManagerDeTest("sans-session");
  signinRedirect.mockRejectedValue(new TypeError("Failed to fetch"));

  rendreRouteGardee(userManager, ["customer"]);

  await waitFor(() => expect(signinRedirect).toHaveBeenCalledTimes(1));
  expect(await screen.findByRole("alert")).toHaveTextContent(MESSAGE_GENERIQUE);
  expect(screen.queryByText("Chargement de la session…")).not.toBeInTheDocument();
  expect(screen.queryByText(CONTENU_PROTEGE)).not.toBeInTheDocument();
});

it("test_pendant_le_chargement_de_la_session_la_garde_affiche_chargement_de_la_session", async () => {
  const { userManager, signinRedirect } = userManagerDeTest("chargement");

  rendreRouteGardee(userManager, ["customer"]);

  expect(await screen.findByRole("status")).toHaveTextContent("Chargement de la session…");
  expect(screen.queryByText(CONTENU_PROTEGE)).not.toBeInTheDocument();
  expect(screen.queryByText("Accès refusé")).not.toBeInTheDocument();
  expect(signinRedirect).not.toHaveBeenCalled();
});

const ROLES: readonly Role[] = ["customer", "partner", "admin"];

it.each(
  ROLES.flatMap((role) =>
    ROLES.map((roleGarde) => ({ role, garde: [roleGarde] as const, admis: role === roleGarde })),
  ),
)(
  "test_chaque_garde_n_admet_que_les_roles_qu_elle_liste (rôle $role, garde $garde)",
  async ({ role, garde, admis }) => {
    const { userManager, signinRedirect } = userManagerDeTest({
      connecte: utilisateurDeTest({ roles: [role] }),
    });

    rendreRouteGardee(userManager, garde);

    if (admis) {
      expect(await screen.findByText(CONTENU_PROTEGE)).toBeInTheDocument();
      expect(screen.queryByText("Accès refusé")).not.toBeInTheDocument();
    } else {
      expect(await attendreAccesRefuse()).toBeInTheDocument();
      expect(screen.queryByText(CONTENU_PROTEGE)).not.toBeInTheDocument();
    }
    expect(signinRedirect).not.toHaveBeenCalled();
  },
);

it.each([
  { role: "partner" as const, admis: true },
  { role: "admin" as const, admis: true },
  { role: "customer" as const, admis: false },
])("test_une_garde_a_plusieurs_roles_admet_chacun_d_eux (rôle $role)", async ({ role, admis }) => {
  const { userManager } = userManagerDeTest({ connecte: utilisateurDeTest({ roles: [role] }) });

  rendreRouteGardee(userManager, ["partner", "admin"]);

  if (admis) {
    expect(await screen.findByText(CONTENU_PROTEGE)).toBeInTheDocument();
  } else {
    expect(await attendreAccesRefuse()).toBeInTheDocument();
    expect(screen.queryByText(CONTENU_PROTEGE)).not.toBeInTheDocument();
  }
});

it("test_un_role_refuse_affiche_acces_refuse_sans_la_page_protegee", async () => {
  const { userManager, signinRedirect } = userManagerDeTest({
    connecte: utilisateurDeTest({ roles: ["customer"], nom: "client.test" }),
  });

  rendreRouteGardee(userManager, ["admin"]);

  expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Accès refusé");
  expect(screen.getByRole("link")).toHaveAttribute("href", "/");
  expect(screen.queryByText(CONTENU_PROTEGE)).not.toBeInTheDocument();
  expect(signinRedirect).not.toHaveBeenCalled();
});

it.each([
  { cas: "sans realm_access", roles: undefined },
  { cas: "realm_access.roles vide", roles: [] },
])(
  "test_un_jeton_sans_role_du_realm_est_refuse_par_toutes_les_gardes ($cas)",
  async ({ roles }) => {
    for (const roleGarde of ROLES) {
      const { userManager } = userManagerDeTest({ connecte: utilisateurDeTest({ roles }) });

      const vue = rendreRouteGardee(userManager, [roleGarde]);

      expect(await attendreAccesRefuse()).toBeInTheDocument();
      expect(screen.queryByText(CONTENU_PROTEGE)).not.toBeInTheDocument();
      vue.unmount();
    }
  },
);

it("test_les_roles_sont_lus_dans_le_jeton_d_acces", async () => {
  const utilisateur = utilisateurDeTest({ roles: ["customer"], rolesIdentite: ["admin"] });

  const gardeAdmin = rendreRouteGardee(userManagerDeTest({ connecte: utilisateur }).userManager, [
    "admin",
  ]);
  expect(await attendreAccesRefuse()).toBeInTheDocument();
  expect(screen.queryByText(CONTENU_PROTEGE)).not.toBeInTheDocument();
  gardeAdmin.unmount();

  rendreRouteGardee(userManagerDeTest({ connecte: utilisateur }).userManager, ["customer"]);
  expect(await screen.findByText(CONTENU_PROTEGE)).toBeInTheDocument();
});
