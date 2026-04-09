# Scénario : prendre N uploads `selected` d’une catégorie

Objectif : parcourir les uploads en `status=selected`, filtrer (catégorie / sous‑catégorie / recherche / regex), puis **prendre** jusqu’à **N** items via `POST /api/upload/take/{id}`.

Commande :

```bash
calewood-toolbox uploads take-selected [OPTIONS]
```

## Ce que fait la commande

1. Appelle `GET /api/upload/list?status=selected` (paginé, `per_page=200`)
2. Applique les filtres côté API (si fournis) : `cat`, `subcat`, `q`, `sort`, `order`
3. Applique les filtres côté Python : regex d’inclusion/exclusion + liste d’IDs only/exclude
4. Pour chaque item retenu : exécute `POST /api/upload/take/{id}` (ou affiche en dry‑run)
5. S’arrête quand **N prises effectives** sont atteintes (`--limit N`)

## Options disponibles

### Filtres côté API (rapides)

- `--cat CAT` : filtre exact `cat=CAT` (optionnel)
- `--subcat SUBCAT` : filtre exact `subcat=SUBCAT` (optionnel)
- `--q Q` : `q=Q` (recherche par nom)
- `--sort COL` : tri côté API (`name`, `size_bytes`, `category`, `seeders`, `selected_at`, `uploaded_at`, `archived_at`)
- `--order asc|desc`

### Filtres côté Python (post‑filtre)

- `--name-regex REGEX` : inclut seulement les noms qui matchent (répétable, insensible à la casse)
- `--exclude-regex REGEX` : exclut les noms qui matchent (répétable, insensible à la casse)

### Filtrage par IDs

Pour ignorer des éléments problématiques sans toucher au reste :

- `--exclude-id ID` (répétable)
- `--exclude-ids "ID1,ID2,..."` (accepte aussi espaces / tabs / retours ligne)

Pour travailler **uniquement** sur une liste d’IDs (ex: liste préparée) :

- `--only-id ID` (répétable)
- `--only-ids "ID1,ID2,..."` (accepte aussi espaces / tabs / retours ligne)

> Si `only_ids` est défini, tous les autres IDs sont ignorés.

### Limite / exécution

- `--limit N` : maximum **N prises effectives** (et la table est limitée à N lignes max)
- `--dry-run` : n’exécute pas les POST (par défaut)
- `--just-do-it` : exécute réellement les POST
- `--verbose` : diagnostics supplémentaires
- `--json` : JSONL à la place du tableau (utile pour piping)

## Exemples

### Prendre 10 uploads d’une catégorie (triés par taille)

```bash
calewood-toolbox uploads take-selected \
  --cat "ebook" \
  --sort size_bytes --order desc \
  --limit 10 \
  --just-do-it --verbose
```

### Ajouter une recherche `q` et filtrer au regex

```bash
calewood-toolbox uploads take-selected \
  --cat "ebook" \
  --q "Asimov" \
  --name-regex "Fondation|Robot" \
  --exclude-regex "tome\\s*1" \
  --limit 10
```

### Exclure une liste d’IDs (copier‑coller)

```bash
calewood-toolbox uploads take-selected \
  --cat "ebook" \
  --exclude-ids "58923 61533 31008 62940" \
  --limit 10
```

### Travailler uniquement sur une liste d’IDs

```bash
calewood-toolbox uploads take-selected \
  --only-ids "58923 61533 31008 62940" \
  --limit 2 \
  --just-do-it --verbose
```

## Comprendre la sortie

La commande affiche :

- un tableau (max `--limit` lignes)
- puis un résumé sur `stderr` :
  - `scanned` : éléments vus (après pagination)
  - `excluded` : IDs explicitement exclus
  - `matched_out` : lignes affichées
  - `attempted` : tentatives de `take`
  - `took` : prises réussies
  - `failed` : prises en erreur

