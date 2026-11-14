// Compte à rebours d'une commande EN_ATTENTE (E04, E05) : calculé sur `expire_le` renvoyé par
// l'API, jamais sur une échéance choisie par le front (contrainte de BIL-020).
import { useEffect, useState } from "react";

/** Millisecondes restantes avant `expireLe` (date de l'API), relues chaque seconde. */
export function useTempsRestant(expireLe: string | undefined): number | null {
  const [maintenant, setMaintenant] = useState(() => Date.now());
  useEffect(() => {
    if (expireLe === undefined) return undefined;
    const minuterie = window.setInterval(() => setMaintenant(Date.now()), 1000);
    return () => window.clearInterval(minuterie);
  }, [expireLe]);
  if (expireLe === undefined) return null;
  return Date.parse(expireLe) - maintenant;
}
