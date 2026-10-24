// Cas composant de BIL-F26 (CA2) : la table des routes sous MemoryRouter et un
// QueryClientProvider de test.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";

import { RoutesApplication } from "./RoutesApplication";

function rendreA(chemin: string) {
  const clientRequetes = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={clientRequetes}>
      <MemoryRouter initialEntries={[chemin]}>
        <RoutesApplication />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("test_la_route_racine_affiche_la_page_d_accueil", () => {
  rendreA("/");

  expect(screen.getByRole("heading", { level: 1, name: "Billetterie" })).toBeInTheDocument();
});

it("test_une_route_inconnue_affiche_la_page_introuvable", () => {
  expect(() => rendreA("/page-inexistante")).not.toThrow();

  expect(screen.getByRole("heading", { level: 1, name: "Page introuvable" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Retour à l'accueil" })).toHaveAttribute("href", "/");
});

// Cas composant de BIL-F28 (CA1, mise en page) : les pages existantes sont rendues dans
// l'unique contenu principal de la mise en page (les pages ne portent plus leur propre <main>).
it.each([
  { chemin: "/", titre: "Billetterie" },
  { chemin: "/route-inconnue", titre: "Page introuvable" },
])(
  "test_les_pages_existantes_s_affichent_dans_un_seul_contenu_principal ($chemin)",
  ({ chemin, titre }) => {
    rendreA(chemin);

    const principaux = screen.getAllByRole("main");
    expect(principaux).toHaveLength(1);
    expect(principaux[0]).toContainElement(screen.getByRole("heading", { level: 1, name: titre }));
    // La mise en page entoure la page : son pied de page est présent.
    expect(screen.getAllByRole("contentinfo")).toHaveLength(1);
  },
);
