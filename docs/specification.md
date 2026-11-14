# Spécification : prévu, réalisé, reporté

État au 2026-11-14. Source du prévu : [conception](conception.md) (lots MVP, V2, V3) et tickets
du board (`BIL-F01` à `BIL-F29` pour les fondations, `BIL-001` et suivants pour le métier). Le
détail de chaque décision est dans `docs/tickets/<ID>.md`.

Le code des tickets BIL-008 à BIL-016 est écrit mais pas encore fusionné : les pull requests
#42 à #53 sont ouvertes et empilées les unes sur les autres, en attente du déblocage du compte
GitHub. Depuis BIL-011, une partie des tests a été reportée à une passe finale (mode allégé du
2026-11-14) : ces lignes sont marquées « à vérifier ».

Légende :

- **Réalisé** : code écrit, tests du ticket écrits et verts.
- **À vérifier** : code écrit ; tests, exécution ou relecture prévus en passe finale.
- **Partiel** : une partie du prévu est livrée, le reste est reporté (justification donnée).
- **Reporté** : prévu, pas réalisé, avec justification.

## User stories

| US | Fonctionnalité | Back | Front | Statut |
|---|---|---|---|---|
| US1 | Consulter événements, lieux et séances | BIL-004, BIL-005 | BIL-019 | À vérifier (1) |
| US2 | Verrouiller une place pendant l'achat | BIL-006, BIL-007 | BIL-020 | À vérifier (1) |
| US3 | Passer commande et payer | BIL-008 | BIL-021 | À vérifier (1) |
| US4 | Recevoir son billet et son QR code | BIL-009 | BIL-021 | À vérifier (1) |
| US5 | Libérer les places non payées | BIL-010 | BIL-021 | À vérifier (1) |
| US6 | Annuler une séance et rembourser | BIL-011 | BIL-022 | À vérifier (2) |
| US7 | API des revendeurs partenaires | BIL-012 | API seule | À vérifier (3) |
| US8 | File d'attente virtuelle | BIL-015 | BIL-023 | Reporté (V2) |

1. Back : tests du ticket écrits et verts dans le pipeline. Front : tests Vitest et
   Playwright, et relecture, reportés à la passe finale.
2. Tests unitaires du plan écrits et verts ; tests d'intégration (60 cas, dont 9 de
   concurrence) reportés à la passe finale.
3. Isolation entre revendeurs et quota testés ; CA2 (parcours partenaire dans Postman) à jouer
   contre la plateforme.

### US1 : consulter le catalogue

- **Réalisé** : lectures publiques paginées, filtres `q`, `ville`, `du`, `au` ; création admin
  d'événements, lieux et séances (`events:write`) ; cache Redis (fraîcheur 30 s, copie de
  secours 24 h signalée par `X-Cache-Stale`) ; jeu de démonstration (`make demo`) ; front avec
  filtres dans l'URL et bandeau de mode dégradé.
- **Écarté** : filtre par catégorie (genre), absent du contrat (BIL-004 Q3, BIL-019).
- **Reporté** : modification d'un événement ou d'une séance, aucune route au contrat (BIL-004
  Q2, BIL-022 Q8).

### US2 : verrouiller une place

- **Réalisé** : verrou Redis `SET NX PX` en Lua (10 minutes, prolongé à 1 heure avant le
  paiement), libération par le seul détenteur, contrainte `uq_billets_place` en base ; preuve
  par test : 100 clients sur une place donnent exactement une vente, dix fois de suite, et la
  base refuse seule la double vente sans Redis (BIL-007) ; plan de salle navigable au clavier,
  compte à rebours calé sur `expire_le` (BIL-020).
- **Écart** : trois états de place à l'écran (libre, indisponible, sélectionnée) au lieu de
  quatre, l'API n'exposant que `disponible` (BIL-018 Q5).

### US3 : commander et payer

- **Réalisé** : commande `EN_ATTENTE` puis verrous, plafond par client et par séance (10),
  paiement simulé (carte de test refusée), `Idempotency-Key`, un seul paiement par commande,
  `ticketing.order.confirmed` par l'outbox (BIL-008) ; commande sans carte puis paiement depuis
  le front, bouton Payer protégé du double clic (BIL-020, BIL-021).

### US4 : recevoir son billet

- **Réalisé** : émission tout ou rien par commande, QR code signé HMAC (`QR_CLE_SIGNATURE`),
  e-mail visible dans Mailpit, anti-doublon par l'historique `envois` (BIL-009) ; écrans
  « Mes commandes » et « Mes billets » avec le QR code (BIL-021).
- **Reporté** : route de scan du QR code (contrôle d'accès, lot V3) ; la vérification existe
  déjà en fonction de domaine de Billets.

### US5 : libérer les places non payées

- **Réalisé** : tâche périodique (30 s) dans Commandes, verrou Redis de tâche pour ne pas
  l'exécuter deux fois avec deux instances, `ticketing.order.expired`, places libérées par
  Billets (BIL-010) ; message clair à l'écran sur une commande expirée (BIL-021).
- **Limite** : une commande restée sans `expire_le` n'expire pas ; écrite dans le README de
  Commandes.

### US6 : annuler une séance

- **Réalisé** : annulation par l'organisateur (rôle `admin`), `ticketing.show.cancelled`,
  remboursement unique de chaque paiement accepté, billets `ANNULE`, e-mails d'annulation et de
  remboursement (BIL-011) ; espace organisateur : création d'événements et de séances, ventes
  par séance, annulation avec confirmation explicite (BIL-022).
- **Reporté** : remboursement d'une commande expirée après un paiement accepté
  (`remboursement_du`, ticket de suivi) ; e-mail de refus sur `ticketing.ticket.rejected`.

### US7 : API des revendeurs

- **Réalisé** : les routes existantes servent le rôle `partner`, toujours filtrées par
  l'appelant du jeton ; hôte Traefik dédié avec un quota de 5 requêtes par seconde par jeton
  (429) ; jeton partenaire refusé sur l'hôte standard ; canal de la commande en base ;
  documentation séparée `docs/contrats/partenaires.yaml` ; lecture de ses billets (BIL-012,
  BIL-021).

### US8 : file d'attente virtuelle

- **Reporté (V2)** : service `file-attente` (BIL-015) et écran E16 (BIL-023, décrit dans
  `docs/front/ecrans.md`). La garantie centrale, aucune double vente, ne dépend pas de la file
  d'attente : elle protège l'expérience pendant le pic, une fois le flux d'achat solide.

## Règles métier de la conception

| # | Règle | Tickets | Statut |
|---|---|---|---|
| 1 | Place verrouillée un temps limité, libérée si non payée | BIL-006, BIL-010 | Réalisé |
| 2 | Jamais deux ventes de la même place | BIL-006, BIL-007 | Réalisé (4) |
| 3 | Plafond de billets par client et par séance | BIL-008 | Réalisé |
| 4 | Billet émis seulement après paiement confirmé | BIL-009 | Réalisé |
| 5 | Annulation d'une séance : remboursement automatique | BIL-011 | À vérifier |
| 6 | Un revendeur ne voit que ses propres commandes | BIL-012 | Réalisé |

4. Avec deux instances de Billets et de Commandes : à vérifier (BIL-013, CA2).

## Fonctions transverses

| Domaine | Tickets | Statut |
|---|---|---|
| Socle des services et contrats | BIL-F08, BIL-001, BIL-002 | Réalisé |
| Sécurité et authentification | BIL-F09, BIL-F10, BIL-F13, BIL-003 | Réalisé |
| Gateway et registre | BIL-F06, BIL-F07 | Réalisé |
| Résilience des appels et des messages | BIL-F11, BIL-F12, BIL-F14 | Réalisé |
| Pannes de l'infrastructure | BIL-F16 | Réalisé |
| Observabilité | BIL-F15, BIL-013 | Réalisé |
| CI | BIL-F04, BIL-007 | Réalisé |
| Deux instances de Billets et Commandes | BIL-013 | À vérifier |
| Pannes des services et démo | BIL-014 | À vérifier |
| Front (socle et écrans E01 à E15) | BIL-F26 à BIL-F28, BIL-018 à BIL-022 | À vérifier |
| Tests de bout en bout du front | BIL-024 | Reporté |
| Vitrine : README, schéma, vidéo | BIL-016 | Partiel |
| Déploiement de la démo en ligne | BIL-F29, BIL-017 | Partiel / reporté |
| Test de charge (k6 ou Gatling) | lot V2 | Reporté |
| Revente, scan du QR code | lot V3 | Reporté |

- **Socle** : cinq services sur le modèle d'echo, une base PostgreSQL par service, contrats
  OpenAPI comparés au code en CI, schémas JSON des événements.
- **Sécurité** : Keycloak (Authorization Code + PKCE pour le front, Client Credentials pour les
  revendeurs et entre services), vérification du jeton à la gateway (ForwardAuth) puis dans
  chaque service, scopes par rôle.
- **Gateway** : Traefik routé par Consul, load balancing sur les instances saines, limitation
  de débit, nouvelles tentatives sur erreur réseau.
- **Résilience** : erreurs Problem Details, identifiant de corrélation, client HTTP avec délai,
  nouvelles tentatives et disjoncteur, outbox transactionnelle, consommateurs idempotents et
  files d'erreur.
- **Pannes de l'infrastructure** : instance echo tuée, RabbitMQ et Consul arrêtés ; 0 erreur
  client sur 301 appels après correctifs (mesures du 2026-10-21, `docs/pannes-infra.md`).
- **Observabilité** : traces OpenTelemetry dans Tempo, métriques Prometheus, tableau de bord
  Grafana (instances, débit, erreurs, files RabbitMQ, répartition par instance).
- **CI** : lint, typage strict, unitaires, intégration, concurrence, contrats, images, gitleaks,
  front.
- **Deux instances** : instances nommées (`billets-1/2`, `commandes-1/2`) plutôt que
  `deploy.replicas`, pour distinguer les instances dans Consul et les journaux ; audit sans
  état en mémoire (BIL-013).
- **Démo** : collection `postman/billetterie.json` (44 requêtes), `scripts/demo.sh`,
  `make parcours` et `make demo-pannes` (BIL-014).
- **Déploiement** : `compose.prod.yaml` et workflow de déploiement manuel écrits (BIL-F29) ;
  VPS, domaine, base Neon et mise en ligne de la plateforme métier non faits (BIL-017).

### Justification des reports

- **Test de charge** : lot V2. La concurrence est prouvée sur une place disputée
  (`make test-concurrence`) ; le comportement global au pic (latences, débit) n'est pas encore
  mesuré.
- **Déploiement en ligne** : VPS, domaine et base Neon pas encore créés ; `compose.prod.yaml`
  n'embarque pas encore les services métier (budget mémoire du VPS, BIL-001). La démo se joue
  en local.
- **Playwright (BIL-024)** : regroupé avec les autres tests du front dans la passe finale, pour
  écrire les parcours une fois tous les écrans en place.
- **E-mails de rappel** (cités par la conception pour Notifications) : planifiés dans aucun
  ticket ; seuls les e-mails de billet, d'annulation et de remboursement sont envoyés.
- **V3 (revente, scan)** : hors du périmètre du projet à ce stade.

## Écarts connus avec la conception

- **Catalogue arrêté** : la conception prévoit « 200 depuis le cache, sinon 503 ». Quand
  l'instance est arrêtée, Traefik n'a plus de route et répond 404 ; le cache n'est servi que si
  c'est la *base* du Catalogue qui tombe, et seulement en appel direct du service (BIL-005,
  BIL-014). Correctifs proposés, en attente de décision : routeur de repli Traefik en 503, et
  check Consul sur une route de vivacité qui ne teste pas la base.
- **Consul en mode dev** : un conteneur Consul recréé repart vide ; les instances ne s'y
  réinscrivent qu'à leur redémarrage (BIL-F16).
- **Limites écrites dans les README des services** : course entre expiration et paiement
  (Commandes, BIL-008), e-mail d'annulation manqué si la confirmation arrive après
  l'annulation (Notifications, BIL-011), doublon d'e-mail possible si le commit échoue après
  l'envoi SMTP (Notifications, BIL-009).

## Reste à vérifier

À faire par le développeur avant de considérer le MVP comme terminé :

1. **Passe finale de tests**
   - Tests d'intégration de BIL-011 (annulation et remboursement, 60 cas dont 9 de
     concurrence), mis de côté pendant le mode allégé.
   - BIL-013 : tests de concurrence rejoués avec deux instances (CA2) ; quatre instances saines
     dans Consul contre `make up` (CA1).
   - Front (BIL-019 à BIL-022) : tests Vitest des écrans, relecture reportée, puis Playwright
     (BIL-024).
   - Smoke tests (`make test-smoke`) contre la plateforme complète.
2. **Exécution de la démo** (BIL-014)
   - `make parcours` : les 44 requêtes de `postman/billetterie.json` vertes avec Newman (CA1),
     dont le parcours partenaire (CA2 de BIL-012).
   - `make demo-pannes` : chaque panne produit la réponse prévue, à l'écart Catalogue près
     (CA2), en moins de 15 minutes (CA3) ; résultats à reporter dans `docs/demo.md`.
3. **Vitrine** (BIL-016)
   - Lancement en suivant le README sur une machine vierge (CA1).
   - Vidéo de 3 minutes en ligne, lien dans le README, le portfolio et la base Projets (CA3).
4. **Décisions en attente** : routeur de repli 503 pour le Catalogue, Newman en CI (workflow
   manuel ou nocturne), remboursement sur `remboursement_du`.
5. **Fusion** : les pull requests #42 à #53, puis celle de ce ticket, une fois le compte GitHub
   débloqué.
