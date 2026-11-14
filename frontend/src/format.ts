// Mise en forme des valeurs de l'API pour l'affichage : dates ISO en heure locale, montants en
// centimes affichés en euros (docs/front/ecrans.md, règles communes).

const FORMAT_DATE_HEURE = new Intl.DateTimeFormat("fr-FR", {
  weekday: "short",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const FORMAT_EUROS = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" });

/** Date et heure ISO 8601 affichées en heure locale (« sam. 12/12/2026 20:00 »). */
export function formaterDateHeure(iso: string): string {
  return FORMAT_DATE_HEURE.format(new Date(iso));
}

const FORMAT_HEURE = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });

/** Heure locale d'une date ISO 8601 (« 20:42 »). */
export function formaterHeure(iso: string): string {
  return FORMAT_HEURE.format(new Date(iso));
}

/** Durée restante en millisecondes affichée « mm:ss » (zéro si elle est négative). */
export function formaterDuree(millisecondes: number): string {
  const secondes = Math.max(0, Math.ceil(millisecondes / 1000));
  const minutes = Math.floor(secondes / 60);
  return `${String(minutes).padStart(2, "0")}:${String(secondes % 60).padStart(2, "0")}`;
}

/** Montant en centimes affiché en euros (« 25,00 € »). */
export function formaterEuros(centimes: number): string {
  return FORMAT_EUROS.format(centimes / 100);
}
