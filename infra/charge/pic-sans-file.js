// Mesure de référence (BIL-015) : pic sur une séance qui n'est PAS sous file d'attente.
// Chaque utilisateur virtuel lit le plan de salle puis commande une place libre, en boucle.
// Exécution locale uniquement, jamais en CI : voir infra/charge/README.md.

import { sleep } from 'k6';
import { commander, jetonDuVu, PIC, placeLibre, SEUILS, verifierConfiguration } from './commun.js';

export const options = {
  scenarios: { pic: PIC },
  thresholds: SEUILS,
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

export function setup() {
  verifierConfiguration();
}

export default function () {
  const jeton = jetonDuVu();
  const place = placeLibre(jeton);
  if (place) {
    commander(jeton, place);
  }
  sleep(1);
}
