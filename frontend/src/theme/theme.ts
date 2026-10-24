// Thème d'affichage exposé par FournisseurTheme, lu par le hook useTheme. Le thème est posé
// par l'attribut `data-theme` de <html> ; le choix manuel est retenu dans localStorage.
import { createContext, useContext } from "react";

export type Theme = "clair" | "sombre";

/** Clé localStorage du choix manuel (préférence d'affichage, jamais de jeton). */
export const CLE_THEME = "billetterie.theme";

export interface ContexteThemeValeur {
  theme: Theme;
  /** Passe au thème opposé et retient ce choix. */
  basculer(): void;
}

/** Valeur hors de tout fournisseur : thème clair, bascule sans effet. */
export const THEME_PAR_DEFAUT: ContexteThemeValeur = {
  theme: "clair",
  basculer: () => {},
};

export const ContexteTheme = createContext<ContexteThemeValeur>(THEME_PAR_DEFAUT);

/** Thème courant (fourni par FournisseurTheme). */
export function useTheme(): ContexteThemeValeur {
  return useContext(ContexteTheme);
}
