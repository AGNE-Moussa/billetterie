// Mise en page commune : lien d'évitement « Aller au contenu », en-tête (navigation, bascule
// de thème, connexion), unique <main id="contenu" tabIndex={-1}> qui reçoit le focus à chaque
// changement de route, pied de page.
import { useEffect, useRef, type MouseEvent, type ReactNode } from "react";
import { useLocation } from "react-router";

import type { LienNavigation } from "../navigation";
import { BasculeTheme } from "./BasculeTheme";
import { EnTete } from "./EnTete";
import styles from "./MiseEnPage.module.css";
import { Navigation } from "./Navigation";
import { PiedDePage } from "./PiedDePage";

export interface ProprietesMiseEnPage {
  children: ReactNode;
  /** Liens de la navigation ; LIENS_NAVIGATION par défaut. */
  liens?: readonly LienNavigation[];
}

const ID_CONTENU = "contenu";

export function MiseEnPage({ children, liens }: ProprietesMiseEnPage) {
  const contenu = useRef<HTMLElement>(null);
  const { pathname } = useLocation();
  const cheminPrecedent = useRef<string | null>(null);

  useEffect(() => {
    // Premier chargement : le focus reste sur le document (le premier Tab atteint le lien
    // d'évitement). Changement de route : le focus passe au nouveau contenu.
    if (cheminPrecedent.current !== null && cheminPrecedent.current !== pathname) {
      contenu.current?.focus();
    }
    cheminPrecedent.current = pathname;
  }, [pathname]);

  const allerAuContenu = (evenement: MouseEvent<HTMLAnchorElement>) => {
    // Le focus est déplacé explicitement : sans cela, certains navigateurs ne font que
    // défiler jusqu'à l'ancre, et l'adresse n'a pas à porter #contenu.
    evenement.preventDefault();
    contenu.current?.focus();
  };

  return (
    <div className={styles.page}>
      <a href={`#${ID_CONTENU}`} className={styles.evitement} onClick={allerAuContenu}>
        Aller au contenu
      </a>
      <EnTete>
        <Navigation liens={liens} />
        <BasculeTheme />
      </EnTete>
      <main id={ID_CONTENU} ref={contenu} tabIndex={-1} className={styles.contenu}>
        {children}
      </main>
      <PiedDePage />
    </div>
  );
}
