# Conventions

Copie versionnée de la section Conventions de la page Notion « Billetterie en ligne ». Ces règles
donnent aux agents IA un cadre stable ; elles sont déclinées en rules dans `.claude/rules/`
(BIL-F18).

- **Contrat d'abord** : chaque service a un fichier OpenAPI 3.1 écrit avant le code. Un test en
  CI compare le schéma généré par FastAPI au contrat validé.
- **Routes** : `/api/v1/<ressource>` en pluriel, verbes HTTP standards, pagination
  `?page=&size=`.
- **Pagination** : une collection répond `{elements, page, size, total}` avec le modèle commun
  `commun.pagination.Page[T]`, sous-classé par ressource pour nommer le schéma du contrat
  (`EchoPage(Page[EchoReponse])`). `page` ≥ 1 (1 par défaut), `size` de 1 à 100 (20 par
  défaut) ; hors bornes : `422 REQUETE_INVALIDE`. Une page au-delà de la fin répond 200 avec
  `elements` vide. L'ordre des éléments est stable et documenté pour chaque ressource.
- **Erreurs** : Problem Details (RFC 9457) avec un code métier stable, par exemple
  `SEAT_ALREADY_TAKEN`. Codes métier des services en anglais (`SEAT_ALREADY_TAKEN`,
  `ORDER_NOT_FOUND`) ; codes techniques de `commun` en français (`REQUETE_INVALIDE`, `JETON_*`,
  `ROLE_MANQUANT`, `SCOPE_MANQUANT`, `BASE_INDISPONIBLE`, `SERVICE_INDISPONIBLE`), et codes
  techniques propres à un service aussi en français (`VERROU_INDISPONIBLE`, billets).
- **Énumérations** : statuts et autres valeurs énumérées en MAJUSCULES sans accent, mots séparés
  par `_` (`EN_ATTENTE`, `CONFIRMEE`).
- **Ressource d'un autre appelant** : une ressource qui existe mais n'appartient pas à l'appelant
  (commande, billet) répond `404 <RESSOURCE>_NOT_FOUND`, comme une ressource inexistante, jamais
  `403` : la réponse ne révèle pas son existence.
- **API partenaires** (BIL-012) : aucune route propre aux revendeurs ; ils appellent les routes
  des services (rôle `partner`, Client Credentials), et leurs commandes sont filtrées par
  l'appelant. Leur documentation publiée, `docs/contrats/partenaires.yaml`, regroupe les
  opérations qui leur sont ouvertes, recopiées à l'identique des contrats de service, plus la
  réponse `429` du quota par jeton de la gateway (chaîne `partenaires@file`). Ce `429` vient de
  Traefik, sans Problem Details, et reste hors des contrats de service. Une route ouverte aux
  revendeurs s'ajoute aux deux contrats.
- **Données** : une base par service, aucune jointure entre services ; on référence un objet d'un
  autre service par son UUID ; montants en centimes.
- **Événements** : nom au passé `ticketing.<entité>.<fait>` ; charge utile versionnée ;
  consommateurs idempotents.
- **Cohérence** : publication via une table outbox, jamais directement.
- **Traçabilité** : identifiant de corrélation créé par la gateway, propagé dans les appels et
  les messages, présent dans chaque ligne de journal.
- **Santé** : `/health` sur chaque service, utilisé par Consul. Les services métier l'exposent
  aussi par la gateway sous `GET /api/v1/<ressource>/health`, avec jeton (chaîne
  `standard@file`), par les tags de `commun.registre.tags_sante_traefik` (réécriture en
  `/health`) ; cette route reste hors contrat. Exception : un service dont les lectures sont
  publiques (préfixe déclaré dans `ROUTES_PUBLIQUES` du vérificateur, qui couvre les
  sous-chemins) expose aussi sa santé sans jeton ; c'est le cas de catalogue
  (`GET /api/v1/events/health`, décision BIL-004) et de billets (`GET /api/v1/seats/health`,
  décision BIL-006), dont le corps `{"statut": "ok"}` ne révèle rien.
- **Configuration** : variables d'environnement uniquement, aucun secret dans le dépôt.
