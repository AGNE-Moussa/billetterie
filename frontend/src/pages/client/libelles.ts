// Libellés des statuts de commande et de billet (E05 à E08), et clés de requête partagées.
import type { StatutBillet } from "../../api/genere/billets";
import type { StatutCommande } from "../../api/genere/commandes";

export const LIBELLES_STATUT_COMMANDE: Readonly<Record<StatutCommande, string>> = {
  EN_ATTENTE: "En attente de paiement",
  CONFIRMEE: "Confirmée",
  EXPIREE: "Expirée",
  REMBOURSEE: "Remboursée",
};

export const LIBELLES_STATUT_BILLET: Readonly<Record<StatutBillet, string>> = {
  EMIS: "Valable",
  ANNULE: "Annulé (séance annulée)",
};

/** Clé de requête des billets d'une commande (E05). */
export function cleBilletsCommande(commandeId: string) {
  return ["billets", "commande", commandeId] as const;
}

/** Clé de requête d'un billet (E07 vers E08). */
export function cleBillet(billetId: string) {
  return ["billets", "billet", billetId] as const;
}
