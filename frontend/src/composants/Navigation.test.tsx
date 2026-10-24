// Cas composant de BIL-F28 (CA1, navigation selon le rôle) : liens publics seuls sans session et
// pendant le chargement, liens du rôle de l'utilisateur sans hiérarchie, lien à plusieurs rôles,
// aria-current="page" sur le lien courant. Session imposée par ContexteSession.Provider ; liens
// synthétiques injectés.
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";

import type { Role } from "../auth/roles";
import { ContexteSession, SESSION_NON_CONNECTEE, type Session } from "../auth/session";
import type { LienNavigation } from "../navigation";
import { Navigation } from "./Navigation";

const LIEN_PUBLIC = "Accueil";
const LIENS_RESERVES = {
  customer: "Lien client de test",
  partner: "Lien partenaire de test",
  admin: "Lien admin de test",
} as const satisfies Record<Role, string>;
const LIEN_SANS_ROLE = "Lien sans rôle de test";

const LIENS_DE_TEST: readonly LienNavigation[] = [
  { libelle: LIEN_PUBLIC, chemin: "/" },
  { libelle: LIENS_RESERVES.customer, chemin: "/espace-client-test", roles: ["customer"] },
  { libelle: LIENS_RESERVES.partner, chemin: "/espace-partenaire-test", roles: ["partner"] },
  { libelle: LIENS_RESERVES.admin, chemin: "/espace-admin-test", roles: ["admin"] },
  // `roles: []` : visible par personne (comme GardeRoles).
  { libelle: LIEN_SANS_ROLE, chemin: "/espace-sans-role-test", roles: [] },
];

const NOMS_UTILISATEUR: Record<Role, string> = {
  customer: "client.test",
  partner: "partenaire.test",
  admin: "admin.test",
};

function sessionConnectee(role: Role): Session {
  return {
    ...SESSION_NON_CONNECTEE,
    statut: "connecte",
    nomUtilisateur: NOMS_UTILISATEUR[role],
    roles: [role],
  };
}

function rendreNavigation(
  session: Session,
  liens: readonly LienNavigation[] = LIENS_DE_TEST,
  chemin = "/",
) {
  return render(
    <ContexteSession.Provider value={session}>
      <MemoryRouter initialEntries={[chemin]}>
        <Navigation liens={liens} />
      </MemoryRouter>
    </ContexteSession.Provider>,
  );
}

function navigationPrincipale() {
  return screen.getByRole("navigation", { name: "Navigation principale" });
}

it("test_sans_session_la_navigation_ne_montre_que_les_liens_publics", () => {
  rendreNavigation(SESSION_NON_CONNECTEE);

  const nav = navigationPrincipale();
  expect(within(nav).getByRole("link", { name: LIEN_PUBLIC })).toHaveAttribute("href", "/");
  for (const libelle of [...Object.values(LIENS_RESERVES), LIEN_SANS_ROLE]) {
    expect(screen.queryByRole("link", { name: libelle })).not.toBeInTheDocument();
  }
});

it("test_pendant_le_chargement_de_la_session_la_navigation_n_affiche_aucun_lien_reserve", () => {
  rendreNavigation({ ...SESSION_NON_CONNECTEE, statut: "chargement" });

  const nav = navigationPrincipale();
  expect(within(nav).getByRole("link", { name: LIEN_PUBLIC })).toBeInTheDocument();
  for (const libelle of [...Object.values(LIENS_RESERVES), LIEN_SANS_ROLE]) {
    expect(screen.queryByText(libelle)).not.toBeInTheDocument();
  }
});

const ROLES: readonly Role[] = ["customer", "partner", "admin"];

it.each(ROLES)("test_la_navigation_montre_les_liens_du_role_de_l_utilisateur (%s)", (role) => {
  rendreNavigation(sessionConnectee(role));

  const nav = navigationPrincipale();
  expect(within(nav).getByRole("link", { name: LIEN_PUBLIC })).toBeInTheDocument();
  expect(within(nav).getByRole("link", { name: LIENS_RESERVES[role] })).toBeInTheDocument();
  for (const autre of ROLES.filter((candidat) => candidat !== role)) {
    expect(screen.queryByRole("link", { name: LIENS_RESERVES[autre] })).not.toBeInTheDocument();
  }
  expect(screen.queryByRole("link", { name: LIEN_SANS_ROLE })).not.toBeInTheDocument();
});

it.each([
  { role: "partner" as const, visible: true },
  { role: "admin" as const, visible: true },
  { role: "customer" as const, visible: false },
])(
  "test_un_lien_reserve_a_plusieurs_roles_apparait_pour_chacun (rôle $role)",
  ({ role, visible }) => {
    const libelle = "Lien partenaire et admin de test";
    rendreNavigation(sessionConnectee(role), [
      { libelle: LIEN_PUBLIC, chemin: "/" },
      { libelle, chemin: "/espace-partenaire-admin-test", roles: ["partner", "admin"] },
    ]);

    const nav = navigationPrincipale();
    expect(within(nav).getByRole("link", { name: LIEN_PUBLIC })).toBeInTheDocument();
    if (visible) {
      expect(within(nav).getByRole("link", { name: libelle })).toBeInTheDocument();
    } else {
      expect(screen.queryByRole("link", { name: libelle })).not.toBeInTheDocument();
    }
  },
);

it("test_le_lien_de_la_page_courante_porte_aria_current_page", () => {
  rendreNavigation(sessionConnectee("customer"), LIENS_DE_TEST, "/espace-client-test");

  const nav = navigationPrincipale();
  expect(within(nav).getByRole("link", { name: LIENS_RESERVES.customer })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(within(nav).getByRole("link", { name: LIEN_PUBLIC })).not.toHaveAttribute("aria-current");
});

it("test_accueil_n_est_le_lien_courant_que_sur_la_racine", () => {
  rendreNavigation(sessionConnectee("customer"), LIENS_DE_TEST, "/");

  const nav = navigationPrincipale();
  expect(within(nav).getByRole("link", { name: LIEN_PUBLIC })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(within(nav).getByRole("link", { name: LIENS_RESERVES.customer })).not.toHaveAttribute(
    "aria-current",
  );
});

it("test_un_lien_reste_courant_sur_ses_sous_chemins", () => {
  // Décision (validation 2) : `end` seulement sur « / ».
  rendreNavigation(sessionConnectee("customer"), LIENS_DE_TEST, "/espace-client-test/detail-test");

  const nav = navigationPrincipale();
  expect(within(nav).getByRole("link", { name: LIENS_RESERVES.customer })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(within(nav).getByRole("link", { name: LIEN_PUBLIC })).not.toHaveAttribute("aria-current");
});
