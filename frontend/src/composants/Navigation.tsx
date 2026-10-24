// Navigation principale (nav « Navigation principale ») : liens publics, puis liens dont l'un
// des rôles est porté par l'utilisateur (sans hiérarchie) ; pendant le chargement de la
// session, liens publics seuls ; aria-current="page" sur le lien courant.
import { NavLink } from "react-router";

import { useSession, type Session } from "../auth/session";
import { LIENS_NAVIGATION, type LienNavigation } from "../navigation";
import styles from "./Navigation.module.css";

export interface ProprietesNavigation {
  /** LIENS_NAVIGATION par défaut. */
  liens?: readonly LienNavigation[];
}

/** Même règle que GardeRoles : public sans `roles`, sinon l'un des rôles de l'utilisateur. */
function estVisible(lien: LienNavigation, { statut, roles }: Session): boolean {
  if (lien.roles === undefined) {
    return true;
  }
  return statut === "connecte" && lien.roles.some((role) => roles.includes(role));
}

export function Navigation({ liens = LIENS_NAVIGATION }: ProprietesNavigation) {
  const session = useSession();
  const visibles = liens.filter((lien) => estVisible(lien, session));

  return (
    <nav aria-label="Navigation principale" className={styles.navigation}>
      <ul className={styles.liste}>
        {visibles.map((lien) => (
          <li key={lien.chemin}>
            {/* `end` sur « / » seul : il n'est pas la page courante des routes qu'il préfixe ;
                les autres liens restent courants sur leurs sous-chemins. */}
            <NavLink to={lien.chemin} end={lien.chemin === "/"} className={styles.lien}>
              {lien.libelle}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
