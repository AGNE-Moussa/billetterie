// En-tête commun à toutes les pages : la marque (logo, non focalisable), puis « Se connecter »
// sans session ; connecté, le preferred_username et « Se déconnecter » ; « Votre session a
// expiré » après un échec du renouvellement. La mise en page y place la navigation et la bascule
// de thème (`children`), avant la connexion dans l'ordre de tabulation.
import type { ReactNode } from "react";
import { useLocation } from "react-router";

import { MESSAGE_SESSION_EXPIREE, useSession } from "../auth/session";
import styles from "./EnTete.module.css";
import { Logo } from "./Logo";

export interface ProprietesEnTete {
  children?: ReactNode;
}

export function EnTete({ children }: ProprietesEnTete) {
  const { statut, nomUtilisateur, sessionExpiree, seConnecter, seDeconnecter } = useSession();
  const { pathname, search, hash } = useLocation();

  return (
    <header className={styles.entete}>
      <div className={styles.interieur}>
        <Logo />
        {children}
        <div className={styles.session}>
          {sessionExpiree && statut !== "connecte" ? (
            <p role="status" className={styles.expiree}>
              {MESSAGE_SESSION_EXPIREE}
            </p>
          ) : null}
          {statut === "connecte" ? (
            <>
              <span className={styles.utilisateur}>
                <span className={styles.avatar} aria-hidden="true">
                  {(nomUtilisateur ?? "?").charAt(0).toUpperCase()}
                </span>
                <span>{nomUtilisateur}</span>
              </span>{" "}
              <button
                type="button"
                className={styles.secondaire}
                onClick={() => void seDeconnecter()}
              >
                Se déconnecter
              </button>
            </>
          ) : null}
          {statut === "non-connecte" ? (
            <button
              type="button"
              className={styles.action}
              onClick={() => void seConnecter(`${pathname}${search}${hash}`)}
            >
              Se connecter
            </button>
          ) : null}
        </div>
      </div>
    </header>
  );
}
