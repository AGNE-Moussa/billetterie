# Git

- Un ticket = une branche = une PR. Branche : celle de la propriété `Branche` du ticket Notion.
- `main` est protégée : aucun push direct, aucune réécriture d'historique.
- Commits en Conventional Commits, en français, sans ligne d'attribution.
- Types : `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`, `perf`, `build`, `style`.
- Aucun agent ne merge : le développeur décide du merge.
- Une décision non prévue par le ticket remonte en question, elle n'est pas tranchée en silence.

```text
Bon      feat(billets): verrouiller une place pendant 10 minutes (BIL-006)
Mauvais  update stuff
Mauvais  feat: wip
Mauvais  Co-Authored-By: ...   (ligne d'attribution interdite)
```
