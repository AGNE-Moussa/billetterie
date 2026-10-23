// Cas composant de BIL-F26 (CA1) : la page d'accueil seule, sous MemoryRouter et un
// QueryClientProvider de test.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";

import { PageAccueil } from "./PageAccueil";

function rendreSousFournisseurs(element: ReactElement) {
  const clientRequetes = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={clientRequetes}>
      <MemoryRouter>{element}</MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

it("test_la_page_d_accueil_s_affiche", () => {
  const erreurConsole = vi.spyOn(console, "error").mockImplementation(() => {});

  rendreSousFournisseurs(<PageAccueil />);

  const principal = screen.getByRole("main");
  expect(principal).toContainElement(
    screen.getByRole("heading", { level: 1, name: "Billetterie" }),
  );
  expect(erreurConsole).not.toHaveBeenCalled();
});
