// Cas composant de BIL-F28 (CA1, thème) : préférence du système tant qu'aucun choix n'est retenu,
// bascule « Thème sombre » (aria-pressed), choix retenu dans localStorage, `data-theme` sur
// <html>. `window.matchMedia` (absent de jsdom) est simulé par le test.
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { BasculeTheme } from "../composants/BasculeTheme";
import { CLE_THEME } from "./theme";
import { FournisseurTheme } from "./FournisseurTheme";

type EcouteurPreference = (evenement: MediaQueryListEvent) => void;

/** `window.matchMedia` simulé : `prefers-color-scheme` suit `sombre`, modifiable par `changer`. */
function simulerPreferenceSysteme(sombreInitial: boolean) {
  let sombre = sombreInitial;
  const listes: { requete: string; ecouteurs: Set<EcouteurPreference>; avant: boolean }[] = [];
  const evaluer = (requete: string) => {
    if (requete.includes("prefers-color-scheme: dark")) {
      return sombre;
    }
    if (requete.includes("prefers-color-scheme: light")) {
      return !sombre;
    }
    return false;
  };
  const matchMedia = (requete: string): MediaQueryList => {
    const entree = { requete, ecouteurs: new Set<EcouteurPreference>(), avant: evaluer(requete) };
    listes.push(entree);
    const ajouter = (ecouteur: unknown) => {
      if (typeof ecouteur === "function") {
        entree.ecouteurs.add(ecouteur as EcouteurPreference);
      }
    };
    const retirer = (ecouteur: unknown) => {
      entree.ecouteurs.delete(ecouteur as EcouteurPreference);
    };
    return {
      media: requete,
      get matches() {
        return evaluer(requete);
      },
      onchange: null,
      addEventListener: (_type: string, ecouteur: unknown) => ajouter(ecouteur),
      removeEventListener: (_type: string, ecouteur: unknown) => retirer(ecouteur),
      addListener: ajouter,
      removeListener: retirer,
      dispatchEvent: () => true,
    } as unknown as MediaQueryList;
  };
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: matchMedia,
  });
  return {
    changer(nouveauSombre: boolean) {
      sombre = nouveauSombre;
      for (const entree of listes) {
        const maintenant = evaluer(entree.requete);
        if (maintenant !== entree.avant) {
          entree.avant = maintenant;
          const evenement = { matches: maintenant, media: entree.requete } as MediaQueryListEvent;
          for (const ecouteur of entree.ecouteurs) {
            ecouteur(evenement);
          }
        }
      }
    },
  };
}

function rendreBascule() {
  return render(
    <FournisseurTheme>
      <BasculeTheme />
    </FournisseurTheme>,
  );
}

function themeAffiche() {
  return document.documentElement.getAttribute("data-theme");
}

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  Reflect.deleteProperty(window, "matchMedia");
});

it.each([
  { preference: "sombre", sombre: true, attendu: "sombre" },
  { preference: "claire", sombre: false, attendu: "clair" },
])(
  "test_sans_choix_enregistre_le_theme_suit_la_preference_du_systeme (préférence $preference)",
  ({ sombre, attendu }) => {
    simulerPreferenceSysteme(sombre);

    rendreBascule();

    expect(themeAffiche()).toBe(attendu);
  },
);

it("test_la_bascule_de_theme_change_le_theme_et_annonce_son_etat", async () => {
  const user = userEvent.setup();
  simulerPreferenceSysteme(false);
  rendreBascule();
  const bascule = screen.getByRole("button", { name: "Thème sombre" });

  await user.click(bascule);
  expect(themeAffiche()).toBe("sombre");
  expect(bascule).toHaveAttribute("aria-pressed", "true");

  bascule.focus();
  await user.keyboard("{Enter}");
  expect(themeAffiche()).toBe("clair");
  expect(bascule).toHaveAttribute("aria-pressed", "false");
});

it("test_le_choix_de_theme_est_retenu_au_rechargement", async () => {
  const user = userEvent.setup();
  simulerPreferenceSysteme(false);
  const premier = rendreBascule();
  await user.click(screen.getByRole("button", { name: "Thème sombre" }));
  expect(themeAffiche()).toBe("sombre");
  premier.unmount();
  document.documentElement.removeAttribute("data-theme");

  simulerPreferenceSysteme(false);
  rendreBascule();

  expect(themeAffiche()).toBe("sombre");
  expect(screen.getByRole("button", { name: "Thème sombre" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  const cles = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index));
  expect(cles).toEqual([CLE_THEME]);
});

it("test_un_changement_de_preference_du_systeme_est_suivi_sans_choix_manuel", async () => {
  const user = userEvent.setup();
  const systeme = simulerPreferenceSysteme(false);
  rendreBascule();
  expect(themeAffiche()).toBe("clair");

  act(() => {
    systeme.changer(true);
  });
  expect(themeAffiche()).toBe("sombre");

  // Choix manuel « clair » (la bascule repasse du sombre au clair), puis le système repasse
  // au clair et revient au sombre.
  await user.click(screen.getByRole("button", { name: "Thème sombre" }));
  expect(themeAffiche()).toBe("clair");
  act(() => {
    systeme.changer(false);
  });
  act(() => {
    systeme.changer(true);
  });

  expect(themeAffiche()).toBe("clair");
});
