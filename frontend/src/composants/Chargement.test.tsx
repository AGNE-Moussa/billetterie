// Cas composant de BIL-F28 (CA1, état commun « chargement ») : role="status", « Chargement… »
// par défaut, libellé remplaçable.
import { render, screen } from "@testing-library/react";

import { Chargement } from "./Chargement";

it("test_l_etat_chargement_est_annonce_en_statut", () => {
  const { rerender } = render(<Chargement />);

  expect(screen.getByRole("status")).toHaveTextContent("Chargement…");

  rerender(<Chargement libelle="Chargement des éléments de test…" />);

  expect(screen.getByRole("status")).toHaveTextContent("Chargement des éléments de test…");
});
