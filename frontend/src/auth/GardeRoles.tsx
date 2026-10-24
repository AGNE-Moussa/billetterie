// Garde de route : rend `children` si l'utilisateur porte l'un des rôles listés (sans
// hiérarchie) ; sans session, redirige vers Keycloak (message générique si la redirection
// échoue) ; sinon, page « Accès refusé ».
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router";

import { Erreur } from "../composants/Erreur";
import { PageAccesRefuse } from "../pages/PageAccesRefuse";
import type { Role } from "./roles";
import { useSession } from "./session";

export interface ProprietesGardeRoles {
  /** Rôles admis : il suffit d'en porter un. */
  roles: readonly Role[];
  children: ReactNode;
}

export function GardeRoles({ roles, children }: ProprietesGardeRoles) {
  const { statut, roles: rolesUtilisateur, seConnecter } = useSession();
  const { pathname, search, hash } = useLocation();
  const redirectionLancee = useRef(false);
  const [redirectionEchouee, setRedirectionEchouee] = useState(false);

  useEffect(() => {
    if (statut === "non-connecte" && !redirectionLancee.current) {
      redirectionLancee.current = true;
      void seConnecter(`${pathname}${search}${hash}`).then((lancee) => {
        if (!lancee) {
          setRedirectionEchouee(true);
        }
      });
    }
  }, [statut, seConnecter, pathname, search, hash]);

  if (statut === "chargement") {
    return <p role="status">Chargement de la session…</p>;
  }
  if (statut === "non-connecte") {
    // Redirection vers Keycloak en cours : rien de protégé n'est rendu.
    // Si elle échoue, le message générique (null n'est pas un problème convertible).
    return redirectionEchouee ? <Erreur probleme={null} /> : null;
  }
  if (!roles.some((role) => rolesUtilisateur.includes(role))) {
    return <PageAccesRefuse />;
  }
  return children;
}
