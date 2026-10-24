// Route /connexion/rappel : « Connexion en cours… », échange du code, puis retour à la page
// demandée ; message générique si le rappel est en erreur.
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router";

import { useSession } from "../auth/session";
import { Erreur } from "../composants/Erreur";

export function PageRappelConnexion() {
  const { terminerConnexion } = useSession();
  const { pathname, search } = useLocation();
  const naviguer = useNavigate();
  const [echec, setEchec] = useState<{ erreur: unknown } | null>(null);
  const echangeLance = useRef(false);

  useEffect(() => {
    // Le code ne s'échange qu'une fois (l'état est consommé par oidc-client-ts).
    if (echangeLance.current) {
      return;
    }
    echangeLance.current = true;
    const adresse = `${window.location.origin}${pathname}${search}`;
    terminerConnexion(adresse).then(
      // `replace` : le code et le state ne restent ni dans l'URL ni dans l'historique.
      (page) => void naviguer(page, { replace: true }),
      (erreur: unknown) => setEchec({ erreur }),
    );
  }, [terminerConnexion, naviguer, pathname, search]);

  return (
    <main>
      {echec === null ? (
        <p role="status">Connexion en cours…</p>
      ) : (
        <Erreur probleme={echec.erreur} />
      )}
    </main>
  );
}
