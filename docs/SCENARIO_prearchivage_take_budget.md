# Scénario : Pré‑archivage (archiviste) — prendre un budget (GiB)

Objectif : prendre des torrents **disponibles** dans le pool pré‑archivage, triés par **taille croissante**, jusqu’à un budget (GiB).

Commande :

```bash
calewood-toolbox prearchivage take-budget-gib GiB [OPTIONS]
```

> Par défaut, `calewood-toolbox` est en **dry‑run**. Pour exécuter réellement : ajouter `--just-do-it`.

## Ce que fait la commande

1. Appelle `GET /api/archive/pre-archivage/list` **sans `status`**  
   → d’après la doc, cela retourne les torrents `selected` **disponibles à prendre**.
2. Applique les filtres côté API si fournis : `q`, `cat`, `subcat`, `seeders`
3. Trie localement par `size_bytes` croissant
4. Additionne les tailles jusqu’à atteindre le budget (GiB)
5. Exécute `POST /api/archive/pre-archivage/take/{id}` sur les éléments retenus (ou affiche en dry‑run)

## Options

- `--q Q` : filtre recherche côté API
- `--cat CAT` / `--subcat SUBCAT` : filtre catégorie / sous‑catégorie (exact)
- `--seeders N` : force `seeders>=N` côté API (0 = désactivé)
- `--max-items N` : limite le nombre maximum d’items à prendre (0 = illimité)

## Exemples

```bash
# Sélectionner jusqu'à 150 GiB (dry-run)
calewood-toolbox prearchivage take-budget-gib 150

# Exécuter réellement
calewood-toolbox --just-do-it prearchivage take-budget-gib 150

# Cibler une catégorie et exiger au moins 1 seeder
calewood-toolbox prearchivage take-budget-gib 150 --cat "Vidéos" --seeders 1

# Limiter le nombre d'items pris
calewood-toolbox prearchivage take-budget-gib 150 --max-items 10
```

