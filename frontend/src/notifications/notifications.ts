// Notifications exposées par FournisseurNotifications, émises par le hook useNotifications.
import { createContext, useContext } from "react";

export type TypeNotification = "succes" | "info" | "erreur";

export interface Notification {
  type: TypeNotification;
  message: string;
}

/** Durée d'affichage d'une notification `succes` ou `info` ; une `erreur` reste affichée. */
export const DUREE_NOTIFICATION_MS = 5000;

export interface ContexteNotificationsValeur {
  /** Affiche une notification ; ne prend jamais le focus. */
  notifier(notification: Notification): void;
}

/** Valeur hors de tout fournisseur : notification sans effet. */
export const NOTIFICATIONS_SANS_FOURNISSEUR: ContexteNotificationsValeur = {
  notifier: () => {},
};

export const ContexteNotifications = createContext<ContexteNotificationsValeur>(
  NOTIFICATIONS_SANS_FOURNISSEUR,
);

/** Émetteur de notifications (fourni par FournisseurNotifications). */
export function useNotifications(): ContexteNotificationsValeur {
  return useContext(ContexteNotifications);
}
