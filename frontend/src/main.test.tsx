// Cas composant de BIL-F28 (validation 2, thème sans flash) : le choix de thème enregistré est
// posé en `data-theme` sur <html> avant `createRoot` dans main.tsx, donc avant le premier rendu
// React. `createRoot` est simulé : le test relève l'attribut au moment de son appel.
import { CLE_THEME } from "./theme/theme";

const releve = vi.hoisted(() => ({
  themeACreateRoot: [] as (string | null)[],
  rendus: 0,
}));

vi.mock("react-dom/client", () => ({
  createRoot: () => {
    releve.themeACreateRoot.push(document.documentElement.getAttribute("data-theme"));
    return {
      render: () => {
        releve.rendus += 1;
      },
      unmount: () => {},
    };
  },
}));

/** `window.matchMedia` simulé : `prefers-color-scheme: dark` vaut `sombre`. */
function simulerPreferenceSysteme(sombre: boolean) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (requete: string) =>
      ({
        media: requete,
        matches: requete.includes("prefers-color-scheme: dark") ? sombre : !sombre,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => true,
      }) as unknown as MediaQueryList,
  });
}

beforeEach(() => {
  vi.resetModules();
  releve.themeACreateRoot = [];
  releve.rendus = 0;
  const racine = document.createElement("div");
  racine.id = "root";
  document.body.append(racine);
});

afterEach(() => {
  document.getElementById("root")?.remove();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  Reflect.deleteProperty(window, "matchMedia");
});

it.each([
  { choix: "sombre", systemeSombre: false },
  { choix: "clair", systemeSombre: true },
])(
  "test_le_choix_de_theme_enregistre_est_pose_avant_le_premier_rendu (choix $choix)",
  async ({ choix, systemeSombre }) => {
    localStorage.setItem(CLE_THEME, choix);
    simulerPreferenceSysteme(systemeSombre);

    await import("./main");

    expect(releve.themeACreateRoot).toHaveLength(1);
    expect(releve.rendus).toBe(1);
    expect(releve.themeACreateRoot[0]).toBe(choix);
  },
);
