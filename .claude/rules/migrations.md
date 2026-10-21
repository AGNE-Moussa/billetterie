---
paths:
  - "**/alembic/**"
---
# Migrations Alembic

- Ne jamais modifier une migration déjà appliquée (mergée sur `main`) : en écrire une nouvelle.
- Une migration par changement, numérotée à la suite (`0003_...`), avec `upgrade` et
  `downgrade`.
- Nommer explicitement les contraintes (`uq_<table>_<colonne>`, `fk_...`) : elles sont
  référencées par le code et par les autres migrations.
- Une contrainte qui protège une règle métier (place vendue une fois) vit en base, pas
  seulement dans le code.
- Tables de messagerie : reprendre la migration type `0002_creer_tables_messagerie.py` d'echo.
- Les mêmes migrations s'appliquent partout (Docker, Neon) : jamais de modification à la main.

```python
# Bon
op.create_table("billets", ..., sa.UniqueConstraint("seance_id", "place", name="uq_billets_place"))

# Mauvais
# éditer 0001_creer_table_echos.py pour y ajouter une colonne
```
