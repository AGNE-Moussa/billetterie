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
  expect(screen.getByRole("link")).toHaveAttribute("href", "/");
});
