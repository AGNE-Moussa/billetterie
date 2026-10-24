// Cas composant de BIL-F28 (CA1, bouton) : bouton natif nommé par son libellé, `type="button"`
// par défaut, désactivé (`disabled` natif), occupé (aria-disabled, focus conservé), variantes.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Bouton, type VarianteBouton } from "./Bouton";

it("test_le_bouton_est_nomme_par_son_libelle_et_declenche_son_action_au_clic_a_entree_et_a_espace", async () => {
  const user = userEvent.setup();
  const surClic = vi.fn();
  render(<Bouton surClic={surClic}>Valider le test</Bouton>);

  const bouton = screen.getByRole("button", { name: "Valider le test" });
  await user.click(bouton);
  bouton.focus();
  await user.keyboard("{Enter}");
  bouton.focus();
  await user.keyboard(" ");

  expect(surClic).toHaveBeenCalledTimes(3);
});

it("test_le_bouton_ne_soumet_pas_de_formulaire_par_defaut", async () => {
  const user = userEvent.setup();
  const surSoumettre = vi.fn();
  const { rerender } = render(
    <form
      aria-label="Formulaire de test"
      onSubmit={(evenement) => {
        evenement.preventDefault();
        surSoumettre();
      }}
    >
      <Bouton>Bouton de test</Bouton>
    </form>,
  );

  const bouton = screen.getByRole("button", { name: "Bouton de test" });
  expect(bouton).toHaveAttribute("type", "button");
  await user.click(bouton);
  expect(surSoumettre).not.toHaveBeenCalled();

  rerender(
    <form
      aria-label="Formulaire de test"
      onSubmit={(evenement) => {
        evenement.preventDefault();
        surSoumettre();
      }}
    >
      <Bouton type="submit">Bouton de test</Bouton>
    </form>,
  );
  await user.click(screen.getByRole("button", { name: "Bouton de test" }));
  expect(surSoumettre).toHaveBeenCalledTimes(1);
});

it("test_un_bouton_desactive_ne_declenche_pas_son_action", async () => {
  const user = userEvent.setup();
  const surClic = vi.fn();
  render(
    <Bouton surClic={surClic} desactive>
      Valider le test
    </Bouton>,
  );

  const bouton = screen.getByRole("button", { name: "Valider le test" });
  expect(bouton).toBeDisabled();
  await user.click(bouton);
  bouton.focus();
  await user.keyboard("{Enter}");

  expect(surClic).not.toHaveBeenCalled();
});

it("test_un_bouton_occupe_est_annonce_occupe_et_ne_declenche_pas_son_action", async () => {
  const user = userEvent.setup();
  const surClic = vi.fn();
  render(
    <Bouton surClic={surClic} occupe>
      Valider le test
    </Bouton>,
  );

  const bouton = screen.getByRole("button", { name: "Valider le test" });
  expect(bouton).toHaveAttribute("aria-busy", "true");
  // Décision (validation 2) : aria-disabled et clic ignoré au lieu de `disabled`, pour garder
  // le focus.
  expect(bouton).toHaveAttribute("aria-disabled", "true");
  expect(bouton).toHaveAccessibleName("Valider le test");
  await user.click(bouton);
  await user.click(bouton);
  bouton.focus();
  await user.keyboard("{Enter}");
  await user.keyboard(" ");

  expect(surClic).not.toHaveBeenCalled();
});

it("test_un_bouton_qui_devient_occupe_garde_le_focus_et_ignore_l_action", async () => {
  const user = userEvent.setup();
  const surClic = vi.fn();
  const { rerender } = render(<Bouton surClic={surClic}>Valider le test</Bouton>);
  const bouton = screen.getByRole("button", { name: "Valider le test" });
  expect(bouton).not.toHaveAttribute("aria-disabled", "true");
  bouton.focus();
  await user.keyboard("{Enter}");
  expect(surClic).toHaveBeenCalledTimes(1);

  rerender(
    <Bouton surClic={surClic} occupe>
      Valider le test
    </Bouton>,
  );

  const boutonOccupe = screen.getByRole("button", { name: "Valider le test" });
  expect(boutonOccupe).toHaveAttribute("aria-disabled", "true");
  expect(boutonOccupe).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(surClic).toHaveBeenCalledTimes(1);
});

it("test_un_bouton_inactif_ignore_son_action_sans_etre_annonce_occupe_et_garde_le_focus", async () => {
  const user = userEvent.setup();
  const surClic = vi.fn();
  render(
    <Bouton surClic={surClic} inactif>
      Valider le test
    </Bouton>,
  );

  const bouton = screen.getByRole("button", { name: "Valider le test" });
  expect(bouton).toHaveAttribute("aria-disabled", "true");
  expect(bouton).not.toHaveAttribute("aria-busy");
  // aria-disabled seul : pas de `disabled` natif, le bouton reste dans l'ordre de tabulation.
  expect(bouton).toBeEnabled();
  expect(bouton).toHaveAccessibleName("Valider le test");

  await user.click(bouton);
  expect(bouton).toHaveFocus();
  await user.keyboard("{Enter}");
  await user.keyboard(" ");

  expect(surClic).not.toHaveBeenCalled();
  expect(bouton).toHaveFocus();
});

// Seconde review, S2 : un `type="submit"` occupé ou inactif ne soumet pas son formulaire. Le cas
// témoin (bouton actif, mêmes gestes) prouve que chaque geste soumet bien quand rien ne l'en
// empêche. La soumission implicite (Entrée dans un champ) n'est pas faite par jsdom mais simulée
// par user-event 14 : un `click` sur le premier bouton de soumission du formulaire, ce que fait
// aussi un navigateur.
type EtatBouton = "actif" | "occupe" | "inactif";
type Geste =
  "clic sur le bouton" | "Entrée sur le bouton" | "Espace sur le bouton" | "Entrée dans le champ";

const GESTES: readonly Geste[] = [
  "clic sur le bouton",
  "Entrée sur le bouton",
  "Espace sur le bouton",
  "Entrée dans le champ",
];

function rendreFormulaire(etat: EtatBouton) {
  const surSoumettre = vi.fn();
  render(
    <form
      aria-label="Formulaire de test"
      onSubmit={(evenement) => {
        evenement.preventDefault();
        surSoumettre();
      }}
    >
      <label>
        Champ de test
        <input type="text" name="champ" />
      </label>
      <Bouton type="submit" occupe={etat === "occupe"} inactif={etat === "inactif"}>
        Envoyer le test
      </Bouton>
    </form>,
  );
  return surSoumettre;
}

async function executer(user: ReturnType<typeof userEvent.setup>, geste: Geste) {
  const bouton = screen.getByRole("button", { name: "Envoyer le test" });
  const champ = screen.getByRole("textbox", { name: "Champ de test" });
  switch (geste) {
    case "clic sur le bouton":
      await user.click(bouton);
      break;
    case "Entrée sur le bouton":
      bouton.focus();
      await user.keyboard("{Enter}");
      break;
    case "Espace sur le bouton":
      bouton.focus();
      await user.keyboard(" ");
      break;
    case "Entrée dans le champ":
      await user.click(champ);
      await user.keyboard("valeur de test{Enter}");
      break;
  }
}

it.each(GESTES)("test_un_bouton_de_soumission_actif_soumet_le_formulaire (%s)", async (geste) => {
  const user = userEvent.setup();
  const surSoumettre = rendreFormulaire("actif");

  await executer(user, geste);

  expect(surSoumettre).toHaveBeenCalledTimes(1);
});

it.each(
  (["occupe", "inactif"] as const).flatMap((etat) => GESTES.map((geste) => ({ etat, geste }))),
)(
  "test_un_bouton_de_soumission_occupe_ou_inactif_ne_soumet_pas_le_formulaire ($etat, $geste)",
  async ({ etat, geste }) => {
    const user = userEvent.setup();
    const surSoumettre = rendreFormulaire(etat);
    expect(screen.getByRole("button", { name: "Envoyer le test" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );

    await executer(user, geste);

    expect(surSoumettre).not.toHaveBeenCalled();
  },
);

const VARIANTES: readonly VarianteBouton[] = ["principal", "secondaire", "danger"];

it.each(VARIANTES)("test_chaque_variante_rend_un_bouton_natif (%s)", (variante) => {
  render(<Bouton variante={variante}>Valider le test</Bouton>);

  const bouton = screen.getByRole("button", { name: "Valider le test" });
  expect(bouton.tagName).toBe("BUTTON");
  expect(bouton).toHaveAccessibleName("Valider le test");
});
