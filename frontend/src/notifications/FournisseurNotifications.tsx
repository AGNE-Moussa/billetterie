// Fournit useNotifications et affiche la pile des notifications dans deux régions live
// permanentes : `succes` / `info` dans role="status", `erreur` dans role="alert". Chaque
// notification a son bouton « Fermer la notification » et sa fermeture automatique (sauf
// `erreur`), suspendue au survol et au focus.
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FocusEvent,
  type ReactNode,
} from "react";

import styles from "./FournisseurNotifications.module.css";
import {
  ContexteNotifications,
  DUREE_NOTIFICATION_MS,
  type ContexteNotificationsValeur,
  type Notification,
} from "./notifications";

export interface ProprietesFournisseurNotifications {
  children: ReactNode;
}

interface NotificationAffichee extends Notification {
  id: number;
}

interface ProprietesElementNotification {
  notification: NotificationAffichee;
  surFermer: (id: number) => void;
}

/** Une notification : sa minuterie (sauf `erreur`) est suspendue au survol et au focus. */
function ElementNotification({ notification, surFermer }: ProprietesElementNotification) {
  const { id, type, message } = notification;
  const [survolee, setSurvolee] = useState(false);
  const [focalisee, setFocalisee] = useState(false);
  const restant = useRef(DUREE_NOTIFICATION_MS);
  const suspendue = survolee || focalisee;

  useEffect(() => {
    if (type === "erreur" || suspendue) {
      return undefined;
    }
    const debut = Date.now();
    const minuterie = window.setTimeout(() => surFermer(id), restant.current);
    return () => {
      window.clearTimeout(minuterie);
      restant.current = Math.max(0, restant.current - (Date.now() - debut));
    };
  }, [id, type, suspendue, surFermer]);

  const surPerteFocus = (evenement: FocusEvent<HTMLDivElement>) => {
    // Le focus reste dans la notification : la minuterie reste suspendue.
    if (!evenement.currentTarget.contains(evenement.relatedTarget)) {
      setFocalisee(false);
    }
  };

  return (
    <div
      className={`${styles.notification ?? ""} ${styles[type] ?? ""}`}
      onMouseEnter={() => setSurvolee(true)}
      onMouseLeave={() => setSurvolee(false)}
      onFocus={() => setFocalisee(true)}
      onBlur={surPerteFocus}
    >
      <p className={styles.message}>{message}</p>
      <button
        type="button"
        className={styles.fermer}
        aria-label="Fermer la notification"
        onClick={() => surFermer(id)}
      >
        <span aria-hidden="true">×</span>
      </button>
    </div>
  );
}

export function FournisseurNotifications({ children }: ProprietesFournisseurNotifications) {
  const [notifications, setNotifications] = useState<readonly NotificationAffichee[]>([]);
  const prochainId = useRef(0);

  const notifier = useCallback((notification: Notification) => {
    prochainId.current += 1;
    const affichee: NotificationAffichee = { ...notification, id: prochainId.current };
    setNotifications((courantes) => [...courantes, affichee]);
  }, []);

  const fermer = useCallback((id: number) => {
    setNotifications((courantes) => courantes.filter((courante) => courante.id !== id));
  }, []);

  const valeur = useMemo<ContexteNotificationsValeur>(() => ({ notifier }), [notifier]);

  const rendre = (filtre: (notification: NotificationAffichee) => boolean) =>
    notifications
      .filter(filtre)
      .map((notification) => (
        <ElementNotification key={notification.id} notification={notification} surFermer={fermer} />
      ));

  return (
    <ContexteNotifications.Provider value={valeur}>
      {children}
      {/* Régions live permanentes, vides au montage : un lecteur d'écran annonce ce qui s'y
          insère, ce qu'il ne fait pas pour une région arrivée déjà remplie. */}
      <div className={styles.pile}>
        <div role="status" aria-atomic="false" className={styles.region}>
          {rendre((notification) => notification.type !== "erreur")}
        </div>
        <div role="alert" aria-atomic="false" className={styles.region}>
          {rendre((notification) => notification.type === "erreur")}
        </div>
      </div>
    </ContexteNotifications.Provider>
  );
}
