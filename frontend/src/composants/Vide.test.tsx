// Cas composant de BIL-F28 (CA1, état commun « vide ») : message et action facultative fournis
// par l'écran.
import { render, screen } from "@testing-library/react";

import { Bouton } from "./Bouton";
import { Vide } from "./Vide";

it("test_l_etat_vide_affiche_le_message_et_l_action_fournis_par_l_ecran", () => {
  const { rerender } = render(
    <Vide message="Aucun élément de test" action={<Bouton>Créer un élément de test</Bouton>} />,
  );

  expect(screen.getByText("Aucun élément de test")).toBeVisible();
  expect(screen.getByRole("button", { name: "Créer un élément de test" })).toBeInTheDocument();

  rerender(<Vide message="Aucun élément de test" />);

  expect(screen.getByText("Aucun élément de test")).toBeVisible();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
