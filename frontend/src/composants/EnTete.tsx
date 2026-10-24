// En-tête commun à toutes les pages : « Se connecter » sans session ; connecté, le
// preferred_username et « Se déconnecter » ; « Votre session a expiré » après un échec du
// renouvellement.
import { useLocation } from "react-router";

import { MESSAGE_SESSION_EXPIREE, useSession } from "../auth/session";

export function EnTete() {
  const { statut, nomUtilisateur, sessionExpiree, seConnecter, seDeconnecter } = useSession();
  const { pathname, search, hash } = useLocation();

  return (
    <header>
      {sessionExpiree && statut !== "connecte" ? (
        <p role="status">{MESSAGE_SESSION_EXPIREE}</p>
      ) : null}
      {statut === "connecte" ? (
        <>
          <span>{nomUtilisateur}</span>{" "}
          <button type="button" onClick={() => void seDeconnecter()}>
            Se déconnecter
          </button>
        </>
      ) : null}
      {statut === "non-connecte" ? (
        <button type="button" onClick={() => void seConnecter(`${pathname}${search}${hash}`)}>
          Se connecter
        </button>
      ) : null}
    </header>
  );
}
