// Outils partagés des scénarios k6 de BIL-015 (pic simulé sur une séance).
// Exécution locale uniquement, jamais en CI : voir infra/charge/README.md.

import http from 'k6/http';
import { check } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

export const BASE_URL = __ENV.BASE_URL || 'http://localhost';
export const SEANCE_ID = __ENV.SEANCE_ID;
// Jetons d'accès clients (rôle customer), séparés par des virgules : l'utilisateur virtuel n
// prend le jeton n modulo leur nombre. Jamais écrits dans ce dépôt.
export const JETONS = (__ENV.JETONS || '').split(',').map((j) => j.trim()).filter((j) => j);

// Pic simulé : montée rapide, plateau, descente (valeurs surchargées par l'environnement).
export const PIC = {
  executor: 'ramping-vus',
  startVUs: 0,
  stages: [
    { duration: __ENV.MONTEE || '10s', target: Number(__ENV.VUS || 200) },
    { duration: __ENV.PLATEAU || '40s', target: Number(__ENV.VUS || 200) },
    { duration: __ENV.DESCENTE || '10s', target: 0 },
  ],
  gracefulRampDown: '5s',
};

// Erreur technique : réseau, délai dépassé ou 5xx. Les refus métier (409 place prise, plafond
// atteint ; 403 admission) sont comptés à part : ils ne mesurent pas la saturation.
export const erreurs = new Rate('erreurs_techniques');
export const refusMetier = new Counter('refus_metier');
export const commandesCreees = new Counter('commandes_creees');
export const dureeCommande = new Trend('duree_creer_commande', true);

export function verifierConfiguration() {
  if (!SEANCE_ID) {
    throw new Error('SEANCE_ID manquant (séance en vente, voir README).');
  }
  if (JETONS.length === 0) {
    throw new Error('JETONS manquant (au moins un jeton client, voir README).');
  }
}

export function jetonDuVu() {
  return JETONS[(__VU - 1) % JETONS.length];
}

export function entetes(jeton, extra = {}) {
  return {
    headers: { Authorization: `Bearer ${jeton}`, 'Content-Type': 'application/json', ...extra },
    timeout: '10s',
  };
}

export function noter(reponse, nom) {
  const technique = reponse.status === 0 || reponse.status >= 500;
  erreurs.add(technique, { requete: nom });
  if (!technique && reponse.status >= 400) {
    refusMetier.add(1, { requete: nom, statut: String(reponse.status) });
  }
  check(reponse, { [`${nom} sans erreur technique`]: () => !technique });
  return !technique && reponse.status < 400;
}

// Une place libre de la séance, au hasard dans la première page (100 places).
export function placeLibre(jeton) {
  const reponse = http.get(
    `${BASE_URL}/api/v1/seats?seance_id=${SEANCE_ID}&size=100`,
    { ...entetes(jeton), tags: { name: 'listerPlaces' } },
  );
  if (!noter(reponse, 'listerPlaces')) {
    return null;
  }
  const libres = reponse.json('elements').filter((place) => place.disponible);
  if (libres.length === 0) {
    return null;
  }
  return libres[Math.floor(Math.random() * libres.length)].id;
}

// Commande d'une place sans carte (201 EN_ATTENTE) : verrou de la place, sans paiement.
export function commander(jeton, placeId, jetonAdmission = null) {
  const extra = jetonAdmission ? { 'X-Admission-Token': jetonAdmission } : {};
  const reponse = http.post(
    `${BASE_URL}/api/v1/orders`,
    JSON.stringify({ seance_id: SEANCE_ID, place_ids: [placeId] }),
    { ...entetes(jeton, extra), tags: { name: 'creerCommande' } },
  );
  dureeCommande.add(reponse.timings.duration);
  if (noter(reponse, 'creerCommande')) {
    commandesCreees.add(1);
  }
  return reponse;
}

export const SEUILS = {
  // Indicatifs : le rapport (docs/charge.md) compare les valeurs mesurées, pas un verdict.
  http_req_duration: ['p(95)<2000'],
  erreurs_techniques: ['rate<0.05'],
};
