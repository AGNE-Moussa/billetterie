// Fournit le thème : préférence du système (prefers-color-scheme) tant qu'aucun choix manuel
// n'est retenu, puis le choix lu dans localStorage ; pose `data-theme` sur <html>. Sa valeur
// initiale est celle que main.tsx a déjà posée avant le premier rendu (mêmes lectures).
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import {
  appliquerTheme,
  lireChoix,
  preferenceSombre,
  retenirChoix,
  themeDuSysteme,
} from "./preference";
import { ContexteTheme, type ContexteThemeValeur, type Theme } from "./theme";

export interface ProprietesFournisseurTheme {
  children: ReactNode;
}

export function FournisseurTheme({ children }: ProprietesFournisseurTheme) {
  const [choix, setChoix] = useState<Theme | null>(lireChoix);
  const [systeme, setSysteme] = useState<Theme>(themeDuSysteme);
  const theme = choix ?? systeme;

  useEffect(() => {
    const liste = preferenceSombre();
    if (liste === null) {
      return undefined;
    }
    const surChangement = (evenement: MediaQueryListEvent) => {
      setSysteme(evenement.matches ? "sombre" : "clair");
    };
    liste.addEventListener("change", surChangement);
    return () => liste.removeEventListener("change", surChangement);
  }, []);

  useEffect(() => {
    appliquerTheme(theme);
  }, [theme]);

  const basculer = useCallback(() => {
    const nouveau: Theme = theme === "sombre" ? "clair" : "sombre";
    retenirChoix(nouveau);
    setChoix(nouveau);
  }, [theme]);

  const valeur = useMemo<ContexteThemeValeur>(() => ({ theme, basculer }), [theme, basculer]);

  return <ContexteTheme.Provider value={valeur}>{children}</ContexteTheme.Provider>;
}
