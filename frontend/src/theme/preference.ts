// Lecture et écriture de la préférence de thème, partagées par main.tsx (thème posé sur <html>
// avant le premier rendu) et FournisseurTheme (même valeur initiale, puis suivi des changements).
import { CLE_THEME, type Theme } from "./theme";

const REQUETE_SOMBRE = "(prefers-color-scheme: dark)";

/** Liste de la préférence sombre du système ; `null` si matchMedia est indisponible. */
export function preferenceSombre(): MediaQueryList | null {
  return typeof window.matchMedia === "function" ? window.matchMedia(REQUETE_SOMBRE) : null;
}

export function themeDuSysteme(): Theme {
  return preferenceSombre()?.matches === true ? "sombre" : "clair";
}

function estTheme(valeur: unknown): valeur is Theme {
  return valeur === "clair" || valeur === "sombre";
}

/** Choix manuel retenu ; `null` sans choix, valeur inconnue ou stockage inaccessible. */
export function lireChoix(): Theme | null {
  try {
    const valeur = window.localStorage.getItem(CLE_THEME);
    return estTheme(valeur) ? valeur : null;
  } catch {
    return null;
  }
}

export function retenirChoix(theme: Theme): void {
  try {
    window.localStorage.setItem(CLE_THEME, theme);
  } catch {
    // Stockage inaccessible (navigation privée stricte) : le choix vaut pour cette visite.
  }
}

export function appliquerTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
}

/** Pose sur <html> le choix retenu, sinon la préférence du système ; renvoie ce thème. */
export function appliquerThemeInitial(): Theme {
  const theme = lireChoix() ?? themeDuSysteme();
  appliquerTheme(theme);
  return theme;
}
