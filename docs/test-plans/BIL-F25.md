# Plan de test : BIL-F25, Workflow : répétition complète sur le service echo

- Ticket : `docs/tickets/BIL-F25.md` ; contrat : `services/echo/openapi.yaml` (opération `listerEchos`)
- Niveaux : unitaire, intégration

Périmètre : la fonctionnalité de l'étape 1 (`GET /api/v1/echos` paginé, scope `echos:read`) et
la section « Décisions ». Les CA1 à CA3 portent sur le workflow (pipeline, hooks,
rétrospective) et n'appellent pas de cas automatisés (voir Q1). Les critères testés ci-dessous
sont donc numérotés D1 à D6, chacun tiré d'une phrase de l'étape 1, des Décisions ou du contrat.

Le ticket ne touche ni Billets ni Commandes : aucun cas de concurrence obligatoire.

Fixtures attendues : unitaire avec `DepotEnMemoire` (étendu à la lecture paginée, dates
`cree_le` distinctes et fixées) et `commun.faux_jetons.EmetteurDeTest` ; intégration sur un
conteneur PostgreSQL 16 dédié au fichier (base vide au départ, migrée par Alembic), instance
`echo-test`.

## Questions

Réponses du développeur (validation 1) :

1. D1 à D6 sont validés comme critères de la fonctionnalité.
2. Deux echos de même `cree_le` : ordre secondaire par `message` croissant (ordre total et
   stable, aucune répétition ni perte entre deux pages).
3. Un paramètre de requête inconnu est ignoré : 200 (comportement par défaut de FastAPI).
4. Le scope `echos:read` est vérifié par un test unitaire du realm
   (`tests/unit/test_realm_keycloak.py`).

Plus aucune question ouverte : plan validé.

## D1 : `GET /api/v1/echos` exige le scope `echos:read` (étape 1, contrat 401/403)

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_lister_les_echos_avec_le_scope_echos_read_renvoie_200` | unitaire | jeton `client="services"`, `scopes=["echos:read"]` ; 2 echos `message-test-01`, `message-test-02` | 200, `application/json`, corps conforme à `EchoPage` |
| `test_sans_jeton_la_liste_repond_401` | unitaire | aucun en-tête `Authorization` | 401, `application/problem+json`, `WWW-Authenticate` commence par `Bearer`, `code` = `JETON_ABSENT` |
| `test_un_jeton_expire_sur_la_liste_recoit_401` | unitaire | jeton `scopes=["echos:read"]`, `expire_dans=-3600` | 401, `code` = `JETON_EXPIRE` |
| `test_un_jeton_avec_seulement_echos_write_recoit_403_sur_la_liste` | unitaire | jeton `client="services"`, `scopes=["echos:write"]` | 403, `application/problem+json`, `code` = `SCOPE_MANQUANT`, `detail` = « Scope requis : echos:read. » |
| `test_un_client_sans_scope_echos_recoit_403_sur_la_liste` | unitaire | jeton `roles=["customer"]`, `scopes=["openid", "profile"]` | 403, `code` = `SCOPE_MANQUANT` |
| `test_le_code_respecte_le_contrat` (existant, doit couvrir `listerEchos` et `EchoPage`) | unitaire | `creer_app` sans base | aucune différence entre `app.openapi()` et `openapi.yaml` |
| `test_le_realm_donne_le_scope_echos_read_par_defaut_au_client_services` (dépend de Q4) | unitaire | lecture de `infra/keycloak/realm-billetterie.json` | le client scope `echos:read` existe et figure dans les scopes par défaut du client `services` |

## D2 : réponse paginée `{elements, page, size, total}`, modèle générique `Page[T]` (Décisions)

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_une_page_generique_serialise_elements_page_size_total` | unitaire | `Page[EchoReponse]` (ou sous-classe de test) avec 2 éléments, `page=1`, `size=20`, `total=2` | `model_dump(mode="json")` a exactement les clés `elements`, `page`, `size`, `total` |
| `test_echo_page_garde_le_nom_du_contrat` | unitaire | `EchoPage.model_json_schema()` | `title` = `EchoPage`, `elements` référence `EchoReponse`, les quatre champs sont requis |
| `test_le_total_compte_tous_les_echos_et_non_ceux_de_la_page` | unitaire | 25 echos `message-test-01` à `message-test-25`, `?size=10` | 200, 10 éléments, `total` = 25 |

## D3 : pagination à partir de 1, `page` ≥ 1 (1 par défaut), `size` de 1 à 100 (20 par défaut)

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_sans_parametres_la_liste_renvoie_la_page_1_de_20_elements` | unitaire | 25 echos, aucun paramètre | 200, `page` = 1, `size` = 20, 20 éléments, `total` = 25 |
| `test_la_derniere_page_contient_le_reste_des_echos` | unitaire | 25 echos, `?page=2&size=20` | 200, `page` = 2, 5 éléments, ce sont les 5 plus anciens |
| `test_les_bornes_de_pagination_sont_acceptees` (paramétré) | unitaire | 3 echos ; `?page=1&size=1` puis `?size=100` | 200 ; 1 élément puis 3 éléments, `size` renvoyé = valeur demandée |
| `test_des_parametres_de_pagination_invalides_renvoient_422_problem_details` (paramétré) | unitaire | `?page=0`, `?page=-1`, `?size=0`, `?size=101`, `?page=abc`, `?size=abc` | 422, `application/problem+json`, `code` = `REQUETE_INVALIDE`, `erreurs[0].champ` commence par `query` |
| `test_les_pages_successives_sur_la_base_ne_repetent_ni_ne_perdent_aucun_echo` (dépend de Q2) | intégration | base vide, 7 echos créés par `POST` (`message-test-01` à `message-test-07`), `?size=3` pages 1, 2, 3 | 3 + 3 + 1 éléments, union = les 7 messages sans doublon, `total` = 7 sur chaque page |

## D4 : éléments au format `EchoReponse`, champ `instance` compris (Décisions)

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_chaque_element_porte_message_instance_et_cree_le` | unitaire | 1 echo `message-test-01`, `cree_le` = `2026-10-20T00:00:00Z`, instance `echo-test` | `elements` = `[{"message": "message-test-01", "instance": "echo-test", "cree_le": "2026-10-20T00:00:00Z"}]` |
| `test_la_liste_relue_en_base_renvoie_le_cree_le_de_la_creation` | intégration | base vide, `POST` de `message-test-01` | l'élément listé a le même `cree_le` que la réponse 201 et `instance` = `echo-test` |

## D5 : tri par `cree_le` décroissant, sans paramètre de tri, aucun filtre (Décisions)

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_les_echos_sont_listes_du_plus_recent_au_plus_ancien` | unitaire | 3 echos insérés dans le désordre, `cree_le` 2026-10-20, 2026-10-22, 2026-10-21 | ordre des `message` : celui du 22, du 21, puis du 20 |
| `test_la_base_renvoie_les_echos_du_plus_recent_au_plus_ancien` | intégration | base vide, 3 `POST` successifs `message-test-01`, `-02`, `-03` | ordre `message-test-03`, `-02`, `-01` ; `cree_le` strictement décroissants |
| `test_des_echos_crees_au_meme_instant_gardent_un_ordre_stable` (dépend de Q2) | intégration | base vide, 10 `POST` lancés en parallèle (`asyncio.gather`), puis 2 lectures complètes `?size=100` et une lecture par pages de 3 | les deux lectures complètes ont le même ordre ; la lecture par pages donne le même ordre sans doublon ni absent |
| `test_un_parametre_de_tri_ou_de_filtre_inconnu_est_ignore` (dépend de Q3) | unitaire | 3 echos, `?tri=message` puis `?message=message-test-01` | 200 avec les 3 echos dans l'ordre par défaut (Q3 : paramètre inconnu ignoré) |

## D6 : page au-delà de la fin : 200 avec `elements` vide (Décisions)

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_une_page_au_dela_de_la_fin_renvoie_200_et_une_liste_vide` | unitaire | 3 echos, `?page=5` | 200, `elements` = `[]`, `page` = 5, `size` = 20, `total` = 3 |
| `test_sans_aucun_echo_la_liste_renvoie_une_page_vide` | unitaire | dépôt vide, aucun paramètre | 200, `{"elements": [], "page": 1, "size": 20, "total": 0}` |
| `test_une_page_au_dela_de_la_fin_sur_la_base_renvoie_une_liste_vide` | intégration | base vide, 2 echos créés, `?page=2&size=2` | 200, `elements` = `[]`, `total` = 2 |

## Couverture

| Critère | Cas |
|---|---|
| CA1, CA2, CA3 | aucun cas automatisé : critères du workflow, vérifiés par le développeur (Q1) |
| D1 | `test_lister_les_echos_avec_le_scope_echos_read_renvoie_200`, `test_sans_jeton_la_liste_repond_401`, `test_un_jeton_expire_sur_la_liste_recoit_401`, `test_un_jeton_avec_seulement_echos_write_recoit_403_sur_la_liste`, `test_un_client_sans_scope_echos_recoit_403_sur_la_liste`, `test_le_code_respecte_le_contrat`, `test_le_realm_donne_le_scope_echos_read_par_defaut_au_client_services` |
| D2 | `test_une_page_generique_serialise_elements_page_size_total`, `test_echo_page_garde_le_nom_du_contrat`, `test_le_total_compte_tous_les_echos_et_non_ceux_de_la_page` |
| D3 | `test_sans_parametres_la_liste_renvoie_la_page_1_de_20_elements`, `test_la_derniere_page_contient_le_reste_des_echos`, `test_les_bornes_de_pagination_sont_acceptees`, `test_des_parametres_de_pagination_invalides_renvoient_422_problem_details`, `test_les_pages_successives_sur_la_base_ne_repetent_ni_ne_perdent_aucun_echo` |
| D4 | `test_chaque_element_porte_message_instance_et_cree_le`, `test_la_liste_relue_en_base_renvoie_le_cree_le_de_la_creation` |
| D5 | `test_les_echos_sont_listes_du_plus_recent_au_plus_ancien`, `test_la_base_renvoie_les_echos_du_plus_recent_au_plus_ancien`, `test_des_echos_crees_au_meme_instant_gardent_un_ordre_stable`, `test_un_parametre_de_tri_ou_de_filtre_inconnu_est_ignore` |
| D6 | `test_une_page_au_dela_de_la_fin_renvoie_200_et_une_liste_vide`, `test_sans_aucun_echo_la_liste_renvoie_une_page_vide`, `test_une_page_au_dela_de_la_fin_sur_la_base_renvoie_une_liste_vide` |
