// Cas composant de BIL-020 (CA2, E03) : plan de salle navigable au clavier. Grille ARIA, une
// seule place dans l'ordre de tabulation, flèches, Début et Fin, Espace ou Entrée pour choisir ;
// chaque place nommée « Rang B, place 12, catégorie Or, 45 euros, libre ». Données synthétiques.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Place } from "../../api/genere/billets";
import type { Categorie } from "../../api/genere/catalogue";
import { PlanSalle } from "./PlanSalle";

const SEANCE_ID = "5e0a0000-0000-4000-8000-000000000001";
const OR: Categorie = {
  id: "ca7e0000-0000-4000-8000-00000000000a",
  nom: "Or",
  prix: 4500,
  rangs: [
    { rang: "A", nombre_places: 3 },
    { rang: "B", nombre_places: 3 },
  ],
};

function place(rang: string, numero: number, disponible = true): Place {
  return {
    id: `${rang}${String(numero)}`,
    seance_id: SEANCE_ID,
    rang,
    numero,
    categorie_id: OR.id,
    disponible,
  };
}

const PLACES: Place[] = [
  place("A", 1),
  place("A", 2, false),
  place("A", 3),
  place("B", 1),
  place("B", 2),
  place("B", 3),
];

function rendrePlan({
  selection = [] as string[],
  lectureSeule = false,
}: { selection?: string[]; lectureSeule?: boolean } = {}) {
  const surBasculer = vi.fn<(place: Place) => void>();
  render(
    <PlanSalle
      places={PLACES}
      categories={new Map([[OR.id, OR]])}
      indicesCategories={new Map([[OR.id, 0]])}
      selection={selection}
      lectureSeule={lectureSeule}
      surBasculer={surBasculer}
    />,
  );
  return { surBasculer };
}

/** Bouton d'une place, par le début de son nom accessible (« Rang A, place 1, »). */
function boutonPlace(rang: string, numero: number) {
  return screen.getByRole("button", {
    name: new RegExp(`^Rang ${rang}, place ${String(numero)},`),
  });
}

it("test_chaque_place_est_nommee_par_rang_numero_categorie_prix_et_etat", () => {
  rendrePlan({ selection: ["B2"] });

  expect(screen.getByRole("grid")).toBeInTheDocument();
  expect(screen.getAllByRole("row")).toHaveLength(2);
  expect(boutonPlace("A", 1)).toHaveAccessibleName(
    /^Rang A, place 1, catégorie Or, 45,00\s€, libre$/,
  );
  expect(boutonPlace("A", 2)).toHaveAccessibleName(/, indisponible$/);
  expect(boutonPlace("B", 2)).toHaveAccessibleName(/, sélectionnée$/);
  expect(boutonPlace("B", 2)).toHaveAttribute("aria-pressed", "true");
});

it("test_une_seule_place_est_dans_l_ordre_de_tabulation", async () => {
  const utilisateur = userEvent.setup();
  rendrePlan();

  await utilisateur.tab();

  expect(boutonPlace("A", 1)).toHaveFocus();
  const tabulables = screen
    .getAllByRole("button")
    .filter((bouton) => bouton.getAttribute("tabindex") === "0");
  expect(tabulables).toEqual([boutonPlace("A", 1)]);
});

it("test_les_fleches_debut_et_fin_deplacent_le_focus_dans_la_grille", async () => {
  const utilisateur = userEvent.setup();
  rendrePlan();
  await utilisateur.tab();

  await utilisateur.keyboard("{ArrowRight}");
  expect(boutonPlace("A", 2)).toHaveFocus();
  await utilisateur.keyboard("{ArrowDown}");
  expect(boutonPlace("B", 2)).toHaveFocus();
  await utilisateur.keyboard("{End}");
  expect(boutonPlace("B", 3)).toHaveFocus();
  await utilisateur.keyboard("{Home}");
  expect(boutonPlace("B", 1)).toHaveFocus();
  await utilisateur.keyboard("{ArrowUp}");
  expect(boutonPlace("A", 1)).toHaveFocus();
  // Bord de la grille : le focus reste en place.
  await utilisateur.keyboard("{ArrowLeft}{ArrowUp}");
  expect(boutonPlace("A", 1)).toHaveFocus();
  // La place active devient la seule tabulable.
  expect(boutonPlace("A", 1)).toHaveAttribute("tabindex", "0");
});

it("test_espace_et_entree_choisissent_la_place_active", async () => {
  const utilisateur = userEvent.setup();
  const { surBasculer } = rendrePlan();
  await utilisateur.tab();

  await utilisateur.keyboard(" ");
  await utilisateur.keyboard("{ArrowDown}{Enter}");

  expect(surBasculer.mock.calls.map(([choisie]) => choisie.id)).toEqual(["A1", "B1"]);
});

it("test_une_place_indisponible_reste_focalisable_mais_ne_peut_pas_etre_choisie", async () => {
  const utilisateur = userEvent.setup();
  const { surBasculer } = rendrePlan();
  await utilisateur.tab();

  await utilisateur.keyboard("{ArrowRight}");
  expect(boutonPlace("A", 2)).toHaveFocus();
  expect(boutonPlace("A", 2)).toHaveAttribute("aria-disabled", "true");
  await utilisateur.keyboard(" ");
  await utilisateur.click(boutonPlace("A", 2));

  expect(surBasculer).not.toHaveBeenCalled();
});

it("test_en_lecture_seule_le_plan_reste_navigable_sans_choix_possible", async () => {
  const utilisateur = userEvent.setup();
  const { surBasculer } = rendrePlan({ lectureSeule: true });
  await utilisateur.tab();

  await utilisateur.keyboard("{ArrowRight}{ArrowRight}");
  expect(boutonPlace("A", 3)).toHaveFocus();
  await utilisateur.keyboard("{Enter}");

  expect(screen.getByRole("grid")).toHaveAttribute("aria-readonly", "true");
  expect(surBasculer).not.toHaveBeenCalled();
});
