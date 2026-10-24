// Bouton natif : `type="button"` par défaut, variantes de présentation. `desactive` pose le
// `disabled` natif. `inactif` et `occupe` posent `aria-disabled="true"` et ignorent l'action
// (clic, Entrée, Espace) sans retirer le focus ; `occupe` ajoute `aria-busy="true"`.
import type { MouseEvent, ReactNode } from "react";

import styles from "./Bouton.module.css";

export type VarianteBouton = "principal" | "secondaire" | "danger";

export interface ProprietesBouton {
  children: ReactNode;
  surClic?: () => void;
  /** `button` par défaut : aucune soumission involontaire. */
  type?: "button" | "submit" | "reset";
  /** Présentation seule ; `principal` par défaut. */
  variante?: VarianteBouton;
  /** `disabled` natif : le bouton sort de l'ordre de tabulation. */
  desactive?: boolean;
  /** Action ignorée, focus conservé (borne atteinte, par exemple). */
  inactif?: boolean;
  /** Action en cours : inactif et annoncé occupé, libellé conservé. */
  occupe?: boolean;
}

export function Bouton({
  children,
  surClic,
  type = "button",
  variante = "principal",
  desactive = false,
  inactif = false,
  occupe = false,
}: ProprietesBouton) {
  const ignore = inactif || occupe;

  const surActivation = (evenement: MouseEvent<HTMLButtonElement>) => {
    if (ignore) {
      // Entrée et Espace passent aussi par `click` : rien n'est déclenché ni soumis.
      evenement.preventDefault();
      return;
    }
    surClic?.();
  };

  return (
    <button
      type={type}
      className={`${styles.bouton ?? ""} ${styles[variante] ?? ""}`}
      disabled={desactive}
      aria-disabled={ignore ? true : undefined}
      aria-busy={occupe ? true : undefined}
      onClick={surActivation}
    >
      {children}
    </button>
  );
}
