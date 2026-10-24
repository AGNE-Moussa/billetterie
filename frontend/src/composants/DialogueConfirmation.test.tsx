// Cas composant de BIL-F28 (CA1, dialogue de confirmation) : <dialog> modal nommé par son titre
// et décrit par son message, focus initial sur « Annuler », Confirmer / Annuler / Échap, clic
// hors du dialogue sans effet, tabulation retenue dans le dialogue, focus rendu au déclencheur.
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import { DialogueConfirmation, type ProprietesDialogueConfirmation } from "./DialogueConfirmation";

// Bouchon de HTMLDialogElement.showModal / close, absents de jsdom (question 6). Il devrait
// vivre dans setupTests.ts ; il est posé ici faute de droit d'écriture sur ce fichier, et ne
// fait rien si showModal existe déjà. Il reproduit le minimum fourni par le navigateur :
// showModal pose `open` (jsdom masque déjà `dialog:not([open])`) et focalise le premier élément
// focalisable ; close retire `open`, rend le focus à l'élément focalisé avant l'ouverture et
// émet `close` ; Échap émet `cancel` (annulable) puis ferme ; Tab et Maj+Tab restent dans le
// dialogue modal (approximation de l'inertie du reste de la page).
function installerBouchonDialogue() {
  if (typeof HTMLDialogElement.prototype.showModal === "function") {
    return;
  }
  const selecteurFocalisable = [
    "a[href]",
    "button:not([disabled])",
    'input:not([disabled]):not([type="hidden"])',
    "select:not([disabled])",
    "textarea:not([disabled])",
    '[tabindex]:not([tabindex="-1"])',
  ].join(", ");
  const modaux: HTMLDialogElement[] = [];
  const focusAvantOuverture = new WeakMap<HTMLDialogElement, HTMLElement | null>();
  const focalisables = (dialogue: HTMLDialogElement) =>
    Array.from(dialogue.querySelectorAll<HTMLElement>(selecteurFocalisable));
  const modalDuDessus = () => {
    const actifs = modaux.filter((dialogue) => dialogue.isConnected && dialogue.open);
    modaux.splice(0, modaux.length, ...actifs);
    return actifs.at(-1);
  };

  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    if (this.open) {
      if (modaux.includes(this)) {
        return;
      }
      throw new DOMException("Dialogue déjà ouvert sans être modal.", "InvalidStateError");
    }
    const actif = document.activeElement;
    focusAvantOuverture.set(this, actif instanceof HTMLElement ? actif : null);
    this.setAttribute("open", "");
    modaux.push(this);
    (this.querySelector<HTMLElement>("[autofocus]") ?? focalisables(this)[0])?.focus();
  };

  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    if (!this.open) {
      return;
    }
    this.removeAttribute("open");
    const index = modaux.indexOf(this);
    if (index !== -1) {
      modaux.splice(index, 1);
    }
    const precedent = focusAvantOuverture.get(this) ?? null;
    focusAvantOuverture.delete(this);
    if (precedent?.isConnected) {
      precedent.focus();
    }
    this.dispatchEvent(new Event("close"));
  };

  document.addEventListener("keydown", (evenement) => {
    const dialogue = modalDuDessus();
    if (evenement.defaultPrevented || dialogue === undefined) {
      return;
    }
    if (evenement.key === "Escape") {
      if (dialogue.dispatchEvent(new Event("cancel", { cancelable: true }))) {
        dialogue.close();
      }
    } else if (evenement.key === "Tab") {
      evenement.preventDefault();
      const elements = focalisables(dialogue);
      const position = elements.indexOf(document.activeElement as HTMLElement);
      const dernier = elements.length - 1;
      const suivant = evenement.shiftKey
        ? position <= 0
          ? dernier
          : position - 1
        : position === -1 || position === dernier
          ? 0
          : position + 1;
      elements[suivant]?.focus();
    }
  });
}

installerBouchonDialogue();

const TITRE = "Confirmer l'action de test";
const MESSAGE = "Cette action de test est définitive.";

function proprietesDeTest(
  surcharges: Partial<ProprietesDialogueConfirmation> = {},
): ProprietesDialogueConfirmation {
  return {
    ouvert: true,
    titre: TITRE,
    message: MESSAGE,
    surConfirmer: vi.fn(),
    surAnnuler: vi.fn(),
    ...surcharges,
  };
}

/** Parent de test : un déclencheur ouvre le dialogue, Confirmer et Annuler le referment. */
function ParentDeTest() {
  const [ouvert, setOuvert] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOuvert(true)}>
        Ouvrir le dialogue de test
      </button>
      <DialogueConfirmation
        ouvert={ouvert}
        titre={TITRE}
        message={MESSAGE}
        surConfirmer={() => setOuvert(false)}
        surAnnuler={() => setOuvert(false)}
      />
    </>
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

it("test_un_dialogue_ferme_n_est_pas_expose", () => {
  // Le passage par l'état ouvert prouve que le dialogue existe : sans lui, « fermé = absent »
  // serait vrai d'un composant qui ne rend rien.
  const { rerender } = render(<DialogueConfirmation {...proprietesDeTest({ ouvert: false })} />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

  rerender(<DialogueConfirmation {...proprietesDeTest({ ouvert: true })} />);
  expect(screen.getByRole("dialog", { name: TITRE })).toBeInTheDocument();

  rerender(<DialogueConfirmation {...proprietesDeTest({ ouvert: false })} />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("test_le_dialogue_ouvert_est_modal_nomme_par_son_titre_et_decrit_par_son_message", () => {
  const showModal = vi.spyOn(HTMLDialogElement.prototype, "showModal");
  render(<DialogueConfirmation {...proprietesDeTest()} />);

  const dialogue = screen.getByRole("dialog");
  expect(dialogue).toHaveAccessibleName(TITRE);
  expect(dialogue).toHaveAccessibleDescription(MESSAGE);
  const modalParAria = dialogue.getAttribute("aria-modal") === "true";
  const modalNatif =
    dialogue instanceof HTMLDialogElement &&
    dialogue.open &&
    showModal.mock.contexts.includes(dialogue);
  expect(modalParAria || modalNatif).toBe(true);
  expect(within(dialogue).getByRole("button", { name: "Confirmer" })).toBeInTheDocument();
  expect(within(dialogue).getByRole("button", { name: "Annuler" })).toBeInTheDocument();
});

it("test_a_l_ouverture_le_focus_va_sur_annuler", () => {
  const { rerender } = render(<DialogueConfirmation {...proprietesDeTest({ ouvert: false })} />);

  rerender(<DialogueConfirmation {...proprietesDeTest({ ouvert: true })} />);

  expect(screen.getByRole("button", { name: "Annuler" })).toHaveFocus();
});

it("test_confirmer_appelle_la_confirmation_une_seule_fois", async () => {
  const user = userEvent.setup();
  const proprietes = proprietesDeTest();
  render(<DialogueConfirmation {...proprietes} />);

  await user.click(screen.getByRole("button", { name: "Confirmer" }));

  expect(proprietes.surConfirmer).toHaveBeenCalledTimes(1);
  expect(proprietes.surAnnuler).not.toHaveBeenCalled();
});

it.each([
  { cas: "clic sur Annuler", annuler: "clic" as const },
  { cas: "Échap", annuler: "echap" as const },
])("test_annuler_et_echap_annulent_sans_confirmer ($cas)", async ({ annuler }) => {
  const user = userEvent.setup();
  const proprietes = proprietesDeTest();
  render(<DialogueConfirmation {...proprietes} />);
  const boutonAnnuler = screen.getByRole("button", { name: "Annuler" });

  if (annuler === "clic") {
    await user.click(boutonAnnuler);
  } else {
    act(() => {
      boutonAnnuler.focus();
    });
    await user.keyboard("{Escape}");
  }

  expect(proprietes.surAnnuler).toHaveBeenCalledTimes(1);
  expect(proprietes.surConfirmer).not.toHaveBeenCalled();
});

it("test_un_clic_hors_du_dialogue_ne_le_ferme_pas", async () => {
  const user = userEvent.setup();
  const proprietes = proprietesDeTest();
  render(<DialogueConfirmation {...proprietes} />);
  const dialogue = screen.getByRole("dialog", { name: TITRE });

  // Un clic sur l'arrière-plan d'un <dialog> modal atteint le dialogue lui-même.
  await user.click(dialogue);

  expect(proprietes.surAnnuler).not.toHaveBeenCalled();
  expect(proprietes.surConfirmer).not.toHaveBeenCalled();
  expect(screen.getByRole("dialog", { name: TITRE })).toBeVisible();
});

it("test_la_tabulation_reste_dans_le_dialogue", async () => {
  const user = userEvent.setup();
  render(
    <>
      <button type="button">Ouvrir le dialogue de test</button>
      <DialogueConfirmation {...proprietesDeTest({ ouvert: true })} />
    </>,
  );
  const declencheur = screen.getByRole("button", { name: "Ouvrir le dialogue de test" });
  const annuler = screen.getByRole("button", { name: "Annuler" });
  const confirmer = screen.getByRole("button", { name: "Confirmer" });
  act(() => {
    annuler.focus();
  });

  for (const sens of ["{Tab}", "{Shift>}{Tab}{/Shift}"]) {
    for (let essai = 0; essai < 4; essai += 1) {
      const avant = document.activeElement;
      await user.keyboard(sens);
      expect(document.activeElement).not.toBe(declencheur);
      expect([annuler, confirmer]).toContain(document.activeElement);
      expect(document.activeElement).not.toBe(avant);
    }
  }
});

it("test_a_la_fermeture_le_focus_revient_au_declencheur", async () => {
  const user = userEvent.setup();
  render(<ParentDeTest />);
  const declencheur = screen.getByRole("button", { name: "Ouvrir le dialogue de test" });

  await user.click(declencheur);
  expect(screen.getByRole("dialog", { name: TITRE })).toBeInTheDocument();
  await user.keyboard("{Escape}");

  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(declencheur).toHaveFocus();
});

it("test_un_dialogue_ferme_par_le_navigateur_appelle_l_annulation", () => {
  const proprietes = proprietesDeTest({ ouvert: true });
  render(<DialogueConfirmation {...proprietes} />);
  const dialogue = screen.getByRole("dialog", { name: TITRE }) as HTMLDialogElement;

  // Second Échap dans Chromium : `cancel` n'est plus annulable et le navigateur ferme le
  // <dialog> lui-même, alors que la prop `ouvert` vaut encore true.
  act(() => {
    dialogue.close();
  });

  expect(proprietes.surAnnuler).toHaveBeenCalledTimes(1);
  expect(proprietes.surConfirmer).not.toHaveBeenCalled();
});

it("test_une_fermeture_demandee_par_la_prop_n_appelle_pas_l_annulation", async () => {
  const user = userEvent.setup();
  const surConfirmer = vi.fn();
  const surAnnuler = vi.fn();
  function ParentEspionne() {
    const [ouvert, setOuvert] = useState(true);
    return (
      <DialogueConfirmation
        ouvert={ouvert}
        titre={TITRE}
        message={MESSAGE}
        surConfirmer={() => {
          surConfirmer();
          setOuvert(false);
        }}
        surAnnuler={surAnnuler}
      />
    );
  }
  render(<ParentEspionne />);

  await user.click(screen.getByRole("button", { name: "Confirmer" }));

  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(surConfirmer).toHaveBeenCalledTimes(1);
  expect(surAnnuler).not.toHaveBeenCalled();
});

it("test_les_libelles_des_boutons_sont_remplacables", () => {
  render(
    <DialogueConfirmation
      {...proprietesDeTest({
        libelleConfirmer: "Supprimer l'élément de test",
        libelleAnnuler: "Garder",
      })}
    />,
  );

  const dialogue = screen.getByRole("dialog", { name: TITRE });
  expect(
    within(dialogue).getByRole("button", { name: "Supprimer l'élément de test" }),
  ).toBeInTheDocument();
  expect(within(dialogue).getByRole("button", { name: "Garder" })).toBeInTheDocument();
  expect(within(dialogue).queryByRole("button", { name: "Confirmer" })).not.toBeInTheDocument();
  expect(within(dialogue).queryByRole("button", { name: "Annuler" })).not.toBeInTheDocument();
});
