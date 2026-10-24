// Rôles du realm billetterie, lus dans realm_access.roles du jeton d'accès (sans hiérarchie).

export type Role = "customer" | "partner" | "admin";

const ROLES_CONNUS: readonly Role[] = ["customer", "partner", "admin"];

function estRole(valeur: unknown): valeur is Role {
  return typeof valeur === "string" && (ROLES_CONNUS as readonly string[]).includes(valeur);
}

/** Charge utile d'un JWT, décodée sans vérifier la signature ; `null` si illisible. */
function chargeUtile(jeton: string): unknown {
  const segment = jeton.split(".")[1];
  if (segment === undefined || segment === "") {
    return null;
  }
  try {
    const base64 = segment.replace(/-/g, "+").replace(/_/g, "/");
    const complete = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
    const octets = Uint8Array.from(atob(complete), (caractere) => caractere.charCodeAt(0));
    return JSON.parse(new TextDecoder().decode(octets)) as unknown;
  } catch {
    return null;
  }
}

/** Rôles connus portés par `realm_access.roles` du jeton d'accès (décodé sans vérification). */
export function rolesDuJeton(jetonAcces: string): Role[] {
  const revendications = chargeUtile(jetonAcces);
  if (typeof revendications !== "object" || revendications === null) {
    return [];
  }
  const acces = (revendications as { realm_access?: unknown }).realm_access;
  if (typeof acces !== "object" || acces === null) {
    return [];
  }
  const roles = (acces as { roles?: unknown }).roles;
  return Array.isArray(roles) ? roles.filter(estRole) : [];
}
