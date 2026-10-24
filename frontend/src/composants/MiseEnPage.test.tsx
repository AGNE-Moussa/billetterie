// Cas composant de BIL-F28 : mise en page (CA1) et navigation complète au clavier (CA2). Rendu
// sous MemoryRouter, FournisseurTheme et FournisseurNotifications (posés par main.tsx, hors de
// MiseEnPage) ; session imposée par ContexteSession.Provider ; liens synthétiques injectés ;
// `window.matchMedia` (absent de jsdom) simulé avec une préférence claire.
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router";

import { ContexteSession, SESSION_NON_CONNECTEE, type Session } from "../auth/session";
import type { LienNavigation } from "../navigation";
import { FournisseurNotifications } from "../notifications/FournisseurNotifications";
import { FournisseurTheme } from "../theme/FournisseurTheme";
import { MiseEnPage } from "./MiseEnPage";

const LIENS_DE_TEST: readonly LienNavigation[] = [
  { libelle: "Accueil", chemin: "/" },
  { libelle: "Lien client de test", chemin: "/espace-client-test", roles: ["customer"] },
  { libelle: "Lien partenaire de test", chemin: "/espace-partenaire-test", roles: ["partner"] },
  { libelle: "Lien admin de test", chemin: "/espace-admin-test", roles: ["admin"] },
];

const SESSION_CLIENT: Session = {
  ...SESSION_NON_CONNECTEE,
  statut: "connecte",
  nomUtilisateur: "client.test",
  roles: ["customer"],
};

/** Préférence système claire, sans changement (la bascule seule change le thème). */
function simulerPreferenceClaire() {
  const matchMedia = (requete: string) =>
    ({
      media: requete,
      matches: requete.includes("prefers-color-scheme: light"),
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => true,
    }) as unknown as MediaQueryList;
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: matchMedia,
  });
}

function rendreMiseEnPage(
  session: Session,
  contenu: ReactNode,
  {
    chemin = "/",
    liens = LIENS_DE_TEST,
  }: { chemin?: string; liens?: readonly LienNavigation[] } = {},
) {
  return render(
    <FournisseurTheme>
      <FournisseurNotifications>
        <ContexteSession.Provider value={session}>
          <MemoryRouter initialEntries={[chemin]}>
            <MiseEnPage liens={liens}>{contenu}</MiseEnPage>
          </MemoryRouter>
        </ContexteSession.Provider>
      </FournisseurNotifications>
    </FournisseurTheme>,
  );
}

function contenuAvecAction() {
  return (
    <>
      <h1>Contenu de test</h1>
      <button type="button">Action du contenu de test</button>
    </>
  );
}

/** Éléments interactifs de la mise en page, dans l'ordre visuel attendu (question 17). */
function ordreAttendu(connecte: boolean): HTMLElement[] {
  const liens = connecte ? ["Accueil", "Lien client de test"] : ["Accueil"];
  return [
    screen.getByRole("link", { name: "Aller au contenu" }),
    ...liens.map((libelle) => screen.getByRole("link", { name: libelle })),
    screen.getByRole("button", { name: "Thème sombre" }),
    screen.getByRole("button", { name: connecte ? "Se déconnecter" : "Se connecter" }),
    screen.getByRole("button", { name: "Action du contenu de test" }),
  ];
}

function partirDuDebutDuDocument() {
  act(() => {
    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
  });
  expect(document.activeElement).toBe(document.body);
}

beforeEach(() => {
  simulerPreferenceClaire();
});

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  Reflect.deleteProperty(window, "matchMedia");
  vi.restoreAllMocks();
});

it("test_la_mise_en_page_porte_l_en_tete_la_navigation_le_contenu_et_le_pied_de_page", () => {
  rendreMiseEnPage(SESSION_NON_CONNECTEE, <h1>Contenu de test</h1>);

  const bandeaux = screen.getAllByRole("banner");
  expect(bandeaux).toHaveLength(1);
  expect(screen.getByRole("navigation", { name: "Navigation principale" })).toBeInTheDocument();
  const principaux = screen.getAllByRole("main");
  expect(principaux).toHaveLength(1);
  expect(within(principaux[0] as HTMLElement).getByText("Contenu de test")).toBeInTheDocument();
  expect(screen.getAllByRole("contentinfo")).toHaveLength(1);
  expect(
    within(bandeaux[0] as HTMLElement).getByRole("button", { name: "Se connecter" }),
  ).toBeInTheDocument();
});

it("test_le_pied_de_page_affiche_son_contenu", () => {
  rendreMiseEnPage(SESSION_CLIENT, <h1>Contenu de test</h1>);

  expect(screen.getByRole("contentinfo")).toHaveTextContent("Billetterie");
});

it.each([
  { cas: "non connecté", session: SESSION_NON_CONNECTEE, connecte: false },
  { cas: "connecté customer", session: SESSION_CLIENT, connecte: true },
])(
  "test_la_tabulation_parcourt_toute_la_mise_en_page_dans_l_ordre_visuel ($cas)",
  async ({ session, connecte }) => {
    const user = userEvent.setup();
    rendreMiseEnPage(session, contenuAvecAction());
    const attendu = ordreAttendu(connecte);
    partirDuDebutDuDocument();

    const parcouru: Element[] = [];
    for (let pas = 0; pas < attendu.length; pas += 1) {
      await user.tab();
      parcouru.push(document.activeElement as Element);
    }

    expect(parcouru).toEqual(attendu);
    await user.tab();
    expect(document.activeElement).toBe(document.body);
  },
);

it("test_maj_tab_parcourt_la_mise_en_page_en_sens_inverse_sans_piege", async () => {
  const user = userEvent.setup();
  rendreMiseEnPage(SESSION_NON_CONNECTEE, contenuAvecAction());
  const attendu = ordreAttendu(false);
  const dernier = attendu.at(-1) as HTMLElement;
  act(() => {
    dernier.focus();
  });

  const parcouru: Element[] = [document.activeElement as Element];
  for (let pas = 1; pas < attendu.length; pas += 1) {
    await user.tab({ shift: true });
    parcouru.push(document.activeElement as Element);
  }

  expect(parcouru).toEqual([...attendu].reverse());
  expect(document.activeElement).toBe(screen.getByRole("link", { name: "Aller au contenu" }));
  await user.tab({ shift: true });
  expect(document.activeElement).toBe(document.body);
});

it("test_le_lien_d_evitement_amene_le_focus_au_contenu_principal", async () => {
  const user = userEvent.setup();
  rendreMiseEnPage(SESSION_NON_CONNECTEE, contenuAvecAction());
  partirDuDebutDuDocument();

  await user.tab();
  expect(screen.getByRole("link", { name: "Aller au contenu" })).toHaveFocus();
  await user.keyboard("{Enter}");

  expect(screen.getByRole("main")).toHaveFocus();
  await user.tab();
  expect(screen.getByRole("button", { name: "Action du contenu de test" })).toHaveFocus();
});

it("test_un_lien_de_navigation_s_active_a_entree_et_deplace_le_focus_sur_le_contenu", async () => {
  const user = userEvent.setup();
  rendreMiseEnPage(
    SESSION_CLIENT,
    <Routes>
      <Route path="/" element={<h1>Accueil de test</h1>} />
      <Route path="/espace-client-test" element={<h1>Espace client de test</h1>} />
    </Routes>,
  );
  const lien = screen.getByRole("link", { name: "Lien client de test" });
  act(() => {
    lien.focus();
  });

  await user.keyboard("{Enter}");

  const titre = screen.getByRole("heading", { level: 1, name: "Espace client de test" });
  expect(screen.queryByRole("heading", { name: "Accueil de test" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Lien client de test" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect([screen.getByRole("main"), titre]).toContain(document.activeElement);
});

it.each([
  { cas: "Se connecter" as const },
  { cas: "Se déconnecter" as const },
  { cas: "bascule de thème" as const },
])("test_les_boutons_de_l_en_tete_s_activent_a_entree_et_a_espace ($cas)", async ({ cas }) => {
  const user = userEvent.setup();
  const seConnecter = vi.fn(() => Promise.resolve(true));
  const seDeconnecter = vi.fn(() => Promise.resolve());
  const session: Session =
    cas === "Se déconnecter"
      ? { ...SESSION_CLIENT, seConnecter, seDeconnecter }
      : { ...SESSION_NON_CONNECTEE, seConnecter, seDeconnecter };
  rendreMiseEnPage(session, <h1>Contenu de test</h1>);
  const nom = cas === "bascule de thème" ? "Thème sombre" : cas;
  const bouton = within(screen.getByRole("banner")).getByRole("button", { name: nom });
  const action = cas === "Se connecter" ? seConnecter : seDeconnecter;
  const etatApres = () =>
    cas === "bascule de thème"
      ? document.documentElement.getAttribute("data-theme")
      : action.mock.calls.length;

  act(() => {
    bouton.focus();
  });
  await user.keyboard("{Enter}");
  expect(etatApres()).toBe(cas === "bascule de thème" ? "sombre" : 1);
  act(() => {
    bouton.focus();
  });
  await user.keyboard(" ");
  expect(etatApres()).toBe(cas === "bascule de thème" ? "clair" : 2);
});
