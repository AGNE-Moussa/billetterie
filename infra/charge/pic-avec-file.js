// Nouvelle mesure (BIL-015) : même pic, sur une séance SOUS file d'attente (SEANCES_SOUS_FILE).
// Chaque utilisateur virtuel entre dans la file, relit sa position jusqu'à son admission, puis
// lit le plan de salle et commande avec son jeton d'admission (X-Admission-Token).
// Exécution locale uniquement, jamais en CI : voir infra/charge/README.md.

import http from 'k6/http';
import { sleep } from 'k6';
import { Trend } from 'k6/metrics';
import {
  BASE_URL,
  SEANCE_ID,
  commander,
  entetes,
  jetonDuVu,
  noter,
  PIC,
  placeLibre,
  SEUILS,
  verifierConfiguration,
} from './commun.js';

// Relecture de la position, en secondes, comme la salle d'attente du front.
const RELECTURE = Number(__ENV.RELECTURE || 2);
// Attente maximale d'une admission dans une itération, en secondes.
const ATTENTE_MAX = Number(__ENV.ATTENTE_MAX || 60);

const attenteAdmission = new Trend('attente_admission', true);

export const options = {
  scenarios: { pic: PIC },
  thresholds: SEUILS,
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

export function setup() {
  verifierConfiguration();
}

function admission(jeton) {
  const url = `${BASE_URL}/api/v1/queues/${SEANCE_ID}/position`;
  const debut = Date.now();
  let reponse = http.post(url, null, { ...entetes(jeton), tags: { name: 'entrerFile' } });
  while (noter(reponse, 'position') && (Date.now() - debut) / 1000 < ATTENTE_MAX) {
    if (reponse.json('statut') === 'ADMIS') {
      attenteAdmission.add(Date.now() - debut);
      return reponse.json('jeton_admission');
    }
    sleep(RELECTURE);
    reponse = http.get(url, { ...entetes(jeton), tags: { name: 'lirePositionFile' } });
  }
  return null;
}

export default function () {
  const jeton = jetonDuVu();
  const jetonAdmission = admission(jeton);
  if (!jetonAdmission) {
    sleep(1);
    return;
  }
  const place = placeLibre(jeton);
  if (place) {
    commander(jeton, place, jetonAdmission);
  }
  sleep(1);
}
