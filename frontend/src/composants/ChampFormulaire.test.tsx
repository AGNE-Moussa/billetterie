// Cas composant de BIL-F28 (CA1, champ de formulaire) : libellé visible associé, champ contrôlé,
// erreur et aide liées par aria-describedby, aria-invalid, obligatoire, identifiants uniques,
// types text, email, number, password, select et textarea.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import { ChampFormulaire, type ProprietesChampFormulaire } from "./ChampFormulaire";

const LIBELLE = "Adresse e-mail";
const ADRESSE = "client.test@exemple.test";
const ERREUR = "Adresse e-mail de test invalide";
const AIDE = "Format nom@domaine";

function sansEffet() {}

/** Parent de test qui retient la valeur remontée par le champ. */
function ChampControle({ surChanger }: { surChanger: (valeur: string) => void }) {
  const [valeur, setValeur] = useState("");
  return (
    <ChampFormulaire
      type="email"
      libelle={LIBELLE}
      valeur={valeur}
      surChanger={(nouvelle) => {
        surChanger(nouvelle);
        setValeur(nouvelle);
      }}
    />
  );
}

it("test_le_champ_est_associe_a_son_libelle_visible", () => {
  render(<ChampFormulaire type="email" libelle={LIBELLE} valeur="" surChanger={sansEffet} />);

  const champ = screen.getByLabelText(LIBELLE);
  expect(screen.getByRole("textbox", { name: LIBELLE })).toBe(champ);
  const libelle = screen.getByText(LIBELLE);
  expect(libelle.closest("label")).not.toBeNull();
  expect(libelle).toBeVisible();
});

it("test_la_saisie_remonte_la_valeur_au_parent", async () => {
  const user = userEvent.setup();
  const surChangerFige = vi.fn();
  const { unmount } = render(
    <ChampFormulaire type="email" libelle={LIBELLE} valeur="" surChanger={surChangerFige} />,
  );

  await user.type(screen.getByLabelText(LIBELLE), "c");
  expect(surChangerFige).toHaveBeenCalledWith("c");
  expect(screen.getByLabelText(LIBELLE)).toHaveValue("");
  unmount();

  const surChanger = vi.fn();
  render(<ChampControle surChanger={surChanger} />);
  await user.type(screen.getByLabelText(LIBELLE), ADRESSE);

  expect(surChanger).toHaveBeenLastCalledWith(ADRESSE);
  expect(screen.getByLabelText(LIBELLE)).toHaveValue(ADRESSE);
});

it("test_un_champ_sans_erreur_n_est_pas_marque_invalide", () => {
  render(<ChampFormulaire type="email" libelle={LIBELLE} valeur="" surChanger={sansEffet} />);

  const champ = screen.getByLabelText(LIBELLE);
  expect(champ).not.toHaveAttribute("aria-invalid", "true");
  expect(champ).toHaveAccessibleDescription("");
});

it("test_un_champ_en_erreur_est_marque_invalide_et_decrit_par_son_message", () => {
  render(
    <ChampFormulaire
      type="email"
      libelle={LIBELLE}
      valeur={ADRESSE}
      surChanger={sansEffet}
      erreur={ERREUR}
    />,
  );

  const champ = screen.getByLabelText(LIBELLE);
  expect(champ).toHaveAttribute("aria-invalid", "true");
  expect(champ).toHaveAccessibleDescription(expect.stringContaining(ERREUR));
  const message = screen.getByText(ERREUR);
  expect(message).toBeVisible();
  expect(champ.compareDocumentPosition(message) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("test_l_aide_et_l_erreur_font_toutes_deux_partie_de_la_description", () => {
  render(
    <ChampFormulaire
      type="email"
      libelle={LIBELLE}
      valeur={ADRESSE}
      surChanger={sansEffet}
      aide={AIDE}
      erreur={ERREUR}
    />,
  );

  const champ = screen.getByLabelText(LIBELLE);
  expect(champ).toHaveAccessibleDescription(expect.stringContaining(AIDE));
  expect(champ).toHaveAccessibleDescription(expect.stringContaining(ERREUR));
});

it("test_un_champ_obligatoire_est_annonce_obligatoire", () => {
  render(
    <ChampFormulaire type="email" libelle={LIBELLE} valeur="" surChanger={sansEffet} obligatoire />,
  );

  const champ = screen.getByRole("textbox", { name: /Adresse e-mail/ });
  expect(champ).toBeRequired();
  expect(champ).toHaveAccessibleName(expect.stringContaining("(obligatoire)"));
});

it("test_deux_champs_du_meme_libelle_ont_des_identifiants_distincts", () => {
  const erreurPremier = "Erreur de test du premier champ";
  const erreurSecond = "Erreur de test du second champ";
  render(
    <>
      <ChampFormulaire
        type="email"
        libelle={LIBELLE}
        valeur=""
        surChanger={sansEffet}
        erreur={erreurPremier}
      />
      <ChampFormulaire
        type="email"
        libelle={LIBELLE}
        valeur=""
        surChanger={sansEffet}
        erreur={erreurSecond}
      />
    </>,
  );

  const champs = screen.getAllByLabelText(LIBELLE);
  expect(champs).toHaveLength(2);
  const [premier, second] = champs as [HTMLElement, HTMLElement];
  expect(premier.id).not.toBe("");
  expect(premier.id).not.toBe(second.id);
  const libelles = screen
    .getAllByText(LIBELLE)
    .map((texte) => texte.closest("label"))
    .filter((libelle): libelle is HTMLLabelElement => libelle !== null);
  expect(libelles.map((libelle) => libelle.control)).toEqual([premier, second]);
  expect(premier).toHaveAccessibleDescription(expect.stringContaining(erreurPremier));
  expect(premier).not.toHaveAccessibleDescription(expect.stringContaining(erreurSecond));
  expect(second).toHaveAccessibleDescription(expect.stringContaining(erreurSecond));
  expect(second).not.toHaveAccessibleDescription(expect.stringContaining(erreurPremier));
});

type TypeChamp = ProprietesChampFormulaire["type"];

const TYPES: readonly { type: TypeChamp; role: string | null }[] = [
  { type: "text", role: "textbox" },
  { type: "email", role: "textbox" },
  { type: "number", role: "spinbutton" },
  { type: "password", role: null },
  { type: "select", role: "combobox" },
  { type: "textarea", role: "textbox" },
];

it.each(TYPES)("test_chaque_type_de_champ_est_associe_a_son_libelle ($type)", ({ type, role }) => {
  const libelle = `Champ de test ${type}`;
  const erreur = `Erreur de test du champ ${type}`;
  const communes = { libelle, surChanger: sansEffet, erreur };
  render(
    type === "select" ? (
      <ChampFormulaire
        {...communes}
        type="select"
        valeur="a"
        options={[
          { valeur: "a", libelle: "Option de test A" },
          { valeur: "b", libelle: "Option de test B" },
        ]}
      />
    ) : (
      <ChampFormulaire {...communes} type={type} valeur="" />
    ),
  );

  const champ = screen.getByLabelText(libelle);
  if (role === null) {
    expect(champ).toHaveAttribute("type", "password");
  } else {
    expect(screen.getByRole(role, { name: libelle })).toBe(champ);
  }
  if (type === "textarea") {
    expect(champ.tagName).toBe("TEXTAREA");
  }
  expect(champ).toHaveAccessibleDescription(expect.stringContaining(erreur));
});
