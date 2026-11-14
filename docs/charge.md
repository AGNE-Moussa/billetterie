# Test de charge : avec et sans file d'attente (BIL-015)

Mesures faites **en local uniquement**, jamais en CI. Scripts et mode d'emploi :
`infra/charge/README.md`.

## Méthode

- Plateforme démarrée (`make up`, `make demo`), une séance de démonstration listée dans
  `SEANCES_SOUS_FILE` pour la seconde mesure.
- **Référence** : `infra/charge/pic-sans-file.js`, pic d'acheteurs sur une seule séance, sans
  file d'attente.
- **Avec file** : `infra/charge/pic-avec-file.js`, entrée dans la file, attente jusqu'à `ADMIS`,
  puis commande avec le jeton d'admission.
- Indicateurs :
  - **latence p95** des appels d'achat (`POST /api/v1/orders`) ;
  - **débit** (requêtes par seconde) ;
  - **taux d'erreur** : réponses réseau en échec, délais dépassés et 5xx ; les refus métier
    (409, 403) sont comptés à part, ce ne sont pas des erreurs de la plateforme.
- Limite connue : les jetons clients sont copiés à la main (`JETONS`) ; avec un seul compte de
  test, tous les utilisateurs virtuels sont le même client. Une mesure réaliste demande
  plusieurs comptes clients de test (décision au développeur).

## Résultats

À compléter après les deux tirs.

| Mesure | Utilisateurs virtuels | p95 achat | Débit | Taux d'erreur | Refus métier |
| --- | --- | --- | --- | --- | --- |
| Sans file | _à mesurer_ | _à mesurer_ | _à mesurer_ | _à mesurer_ | _à mesurer_ |
| Avec file | _à mesurer_ | _à mesurer_ | _à mesurer_ | _à mesurer_ | _à mesurer_ |

## Lecture

À rédiger : comparaison du p95 et du taux d'erreur avant et après (CA2), et vérification
qu'aucune place n'est vendue deux fois pendant le pic.
