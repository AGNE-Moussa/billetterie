// Cas composant de BIL-F28 (CA1, tableau paginé) : tableau nommé, en-têtes de colonnes, lignes,
// pagination contrôlée « Page <page> sur <nombre> » sans requête, bornes, état vide, état occupé,
// pagination au clavier. Validation 2 : aria-disabled au lieu de `disabled` (focus conservé à la
// borne), clés de colonnes uniques, position annoncée, zone de défilement focalisable et nommée.
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import { serveurMsw } from "../mocks/serveur";
import { TableauPagine, type ColonneTableau, type Page } from "./TableauPagine";

interface LigneDeTest {
  id: string;
  libelle: string;
  montant_centimes: number;
}

const NOM_TABLEAU = "Éléments de test";
const MESSAGE_VIDE = "Aucun élément de test";

const COLONNES: readonly ColonneTableau<LigneDeTest>[] = [
  { entete: "Libellé", rendu: (ligne) => ligne.libelle },
  { entete: "Montant (centimes)", rendu: (ligne) => String(ligne.montant_centimes) },
];

function lignesDeTest(nombre: number): LigneDeTest[] {
  return Array.from({ length: nombre }, (_, index) => ({
    id: crypto.randomUUID(),
    libelle: `Élément de test ${String(index + 1)}`,
    montant_centimes: (index + 1) * 1250,
  }));
}

function pageDeTest(page: number, total: number, nombre = 3): Page<LigneDeTest> {
  return { elements: lignesDeTest(nombre), page, size: 20, total };
}

function rendreTableau(
  page: Page<LigneDeTest>,
  surChangerPage: (numero: number) => void = () => {},
  occupe = false,
) {
  return render(
    <TableauPagine
      libelle={NOM_TABLEAU}
      colonnes={COLONNES}
      page={page}
      cleLigne={(ligne) => ligne.id}
      surChangerPage={surChangerPage}
      messageVide={MESSAGE_VIDE}
      occupe={occupe}
    />,
  );
}

function pagination() {
  return screen.getByRole("navigation", { name: "Pagination" });
}

/** Conteneur focalisable (tabindex="0") qui entoure le tableau, `null` si aucun. */
function zoneDeDefilement() {
  return screen.getByRole("table", { name: NOM_TABLEAU }).closest<HTMLElement>('[tabindex="0"]');
}

afterEach(() => {
  serveurMsw.events.removeAllListeners();
  vi.restoreAllMocks();
});

it("test_le_tableau_rend_un_tableau_nomme_avec_en_tetes_de_colonnes_et_lignes", () => {
  const page = pageDeTest(1, 3);
  rendreTableau(page);

  const tableau = screen.getByRole("table", { name: NOM_TABLEAU });
  const entetes = within(tableau).getAllByRole("columnheader");
  expect(entetes.map((entete) => entete.textContent)).toEqual(["Libellé", "Montant (centimes)"]);
  const lignesDeDonnees = within(tableau)
    .getAllByRole("row")
    .filter((ligne) => within(ligne).queryAllByRole("columnheader").length === 0);
  expect(lignesDeDonnees).toHaveLength(3);
  page.elements.forEach((element, index) => {
    const ligne = lignesDeDonnees[index] as HTMLElement;
    expect(within(ligne).getByRole("cell", { name: element.libelle })).toBeInTheDocument();
    expect(
      within(ligne).getByRole("cell", { name: String(element.montant_centimes) }),
    ).toBeInTheDocument();
  });
});

it("test_la_pagination_affiche_la_page_courante_sur_le_nombre_de_pages", () => {
  rendreTableau(pageDeTest(2, 45));

  expect(within(pagination()).getByText("Page 2 sur 3")).toBeInTheDocument();
});

it("test_page_suivante_et_page_precedente_demandent_la_page_voisine_sans_requete", async () => {
  const user = userEvent.setup();
  const requetes: string[] = [];
  serveurMsw.events.on("request:start", ({ request }) => {
    requetes.push(request.url);
  });
  const surChangerPage = vi.fn();
  rendreTableau(pageDeTest(2, 45), surChangerPage);

  await user.click(within(pagination()).getByRole("button", { name: "Page suivante" }));
  expect(surChangerPage).toHaveBeenLastCalledWith(3);
  await user.click(within(pagination()).getByRole("button", { name: "Page précédente" }));
  expect(surChangerPage).toHaveBeenLastCalledWith(1);

  expect(surChangerPage).toHaveBeenCalledTimes(2);
  expect(within(pagination()).getByText("Page 2 sur 3")).toBeInTheDocument();
  expect(requetes).toEqual([]);
});

it.each([
  { cas: "première page", page: 1, total: 45, precedenteBloquee: true, suivanteBloquee: false },
  { cas: "dernière page", page: 3, total: 45, precedenteBloquee: false, suivanteBloquee: true },
  { cas: "une seule page", page: 1, total: 5, precedenteBloquee: true, suivanteBloquee: true },
])(
  "test_les_commandes_de_pagination_sont_desactivees_aux_bornes ($cas)",
  async ({ cas, page, total, precedenteBloquee, suivanteBloquee }) => {
    const user = userEvent.setup();
    const surChangerPage = vi.fn();
    rendreTableau(pageDeTest(page, total), surChangerPage);

    expect(screen.getByRole("table", { name: NOM_TABLEAU })).toBeInTheDocument();
    const nav = screen.queryByRole("navigation", { name: "Pagination" });
    if (cas === "une seule page" && nav === null) {
      // Pagination masquée sur une seule page : admis par le plan (question 9).
      return;
    }
    expect(nav).not.toBeNull();
    const boutonPrecedent = within(nav as HTMLElement).getByRole("button", {
      name: "Page précédente",
    });
    const boutonSuivant = within(nav as HTMLElement).getByRole("button", { name: "Page suivante" });
    // Décision (validation 2) : aria-disabled et clic ignoré au lieu de `disabled`.
    for (const [bouton, bloque] of [
      [boutonPrecedent, precedenteBloquee],
      [boutonSuivant, suivanteBloquee],
    ] as const) {
      if (bloque) {
        expect(bouton).toHaveAttribute("aria-disabled", "true");
        await user.click(bouton);
      } else {
        expect(bouton).toBeEnabled();
        expect(bouton).not.toHaveAttribute("aria-disabled", "true");
      }
    }
    expect(surChangerPage).not.toHaveBeenCalled();
  },
);

/** Parent de test : tient la page courante et la remplace à chaque demande. */
function TableauControle({ total }: { total: number }) {
  const [page, setPage] = useState(() => pageDeTest(2, total));
  return (
    <TableauPagine
      libelle={NOM_TABLEAU}
      colonnes={COLONNES}
      page={page}
      cleLigne={(ligne) => ligne.id}
      surChangerPage={(numero) => setPage(pageDeTest(numero, total))}
      messageVide={MESSAGE_VIDE}
    />
  );
}

it.each([
  { cas: "Page suivante vers la dernière page", bouton: "Page suivante", attendu: "Page 3 sur 3" },
  {
    cas: "Page précédente vers la première page",
    bouton: "Page précédente",
    attendu: "Page 1 sur 3",
  },
])(
  "test_un_bouton_de_pagination_qui_atteint_la_borne_garde_le_focus ($cas)",
  async ({ bouton, attendu }) => {
    const user = userEvent.setup();
    render(<TableauControle total={45} />);
    const cible = within(pagination()).getByRole("button", { name: bouton });
    act(() => {
      cible.focus();
    });

    await user.keyboard("{Enter}");

    expect(within(pagination()).getByText(attendu)).toBeInTheDocument();
    const apres = within(pagination()).getByRole("button", { name: bouton });
    expect(apres).toHaveAttribute("aria-disabled", "true");
    expect(apres).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(within(pagination()).getByText(attendu)).toBeInTheDocument();
  },
);

it("test_deux_colonnes_au_meme_en_tete_se_rendent_sans_avertissement_de_cle", () => {
  const erreurs = vi.spyOn(console, "error").mockImplementation(() => {});
  const colonnes: readonly ColonneTableau<LigneDeTest>[] = [
    { entete: "Colonne de test", rendu: (ligne) => ligne.libelle },
    { entete: "Colonne de test", rendu: (ligne) => String(ligne.montant_centimes) },
  ];
  const page = pageDeTest(1, 1, 1);
  render(
    <TableauPagine
      libelle={NOM_TABLEAU}
      colonnes={colonnes}
      page={page}
      cleLigne={(ligne) => ligne.id}
      surChangerPage={() => {}}
      messageVide={MESSAGE_VIDE}
    />,
  );

  const tableau = screen.getByRole("table", { name: NOM_TABLEAU });
  expect(within(tableau).getAllByRole("columnheader")).toHaveLength(2);
  const element = page.elements[0] as LigneDeTest;
  expect(within(tableau).getByRole("cell", { name: element.libelle })).toBeInTheDocument();
  expect(
    within(tableau).getByRole("cell", { name: String(element.montant_centimes) }),
  ).toBeInTheDocument();
  expect(erreurs).not.toHaveBeenCalled();
});

it("test_la_position_page_x_sur_y_est_dans_une_zone_annoncee", () => {
  rendreTableau(pageDeTest(2, 45));

  const position = within(pagination()).getByText("Page 2 sur 3");
  const zone = position.closest('[aria-live="polite"], [role="status"]');
  expect(zone).not.toBeNull();
});

it("test_la_zone_de_defilement_du_tableau_est_focalisable_et_nommee", () => {
  rendreTableau(pageDeTest(1, 3));

  const zone = zoneDeDefilement();
  expect(zone).not.toBeNull();
  expect(zone).toHaveAttribute("tabindex", "0");
  expect(zone).toHaveAccessibleName();
});

it("test_un_tableau_sans_element_affiche_l_etat_vide", () => {
  rendreTableau({ elements: [], page: 1, size: 20, total: 0 });

  expect(screen.getByText(MESSAGE_VIDE)).toBeVisible();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "Pagination" })).not.toBeInTheDocument();
});

it("test_un_tableau_occupe_est_annonce_occupe_et_bloque_la_pagination", async () => {
  const user = userEvent.setup();
  const surChangerPage = vi.fn();
  rendreTableau(pageDeTest(2, 45), surChangerPage, true);

  expect(screen.getByRole("table", { name: NOM_TABLEAU })).toHaveAttribute("aria-busy", "true");
  const precedente = within(pagination()).getByRole("button", { name: "Page précédente" });
  const suivante = within(pagination()).getByRole("button", { name: "Page suivante" });
  expect(precedente).toHaveAttribute("aria-disabled", "true");
  expect(suivante).toHaveAttribute("aria-disabled", "true");
  await user.click(precedente);
  await user.click(suivante);
  act(() => {
    suivante.focus();
  });
  await user.keyboard("{Enter}");

  expect(surChangerPage).not.toHaveBeenCalled();
});

it("test_la_pagination_se_manipule_au_clavier", async () => {
  const user = userEvent.setup();
  const surChangerPage = vi.fn();
  rendreTableau(pageDeTest(2, 45), surChangerPage);
  const precedente = within(pagination()).getByRole("button", { name: "Page précédente" });
  const suivante = within(pagination()).getByRole("button", { name: "Page suivante" });

  // Zone de défilement focalisable (validation 2) : premier arrêt de tabulation du tableau.
  const zone = zoneDeDefilement();
  expect(zone).not.toBeNull();
  await user.tab();
  expect(zone).toHaveFocus();
  await user.tab();
  expect(precedente).toHaveFocus();
  await user.tab();
  expect(suivante).toHaveFocus();
  await user.keyboard("{Enter}");

  expect(surChangerPage).toHaveBeenCalledTimes(1);
  expect(surChangerPage).toHaveBeenCalledWith(3);
});
