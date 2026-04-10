# Scénario : Archivage classique — prendre les plus petits / prendre un budget (GiB)

Objectif : sélectionner des items **disponibles** à archiver (par défaut `status=uploaded`), triés par **taille croissante**, puis les **prendre** via `POST /api/archive/take/{id}`.

Deux variantes :

- **N plus petits** : `archives take-smallest N`
- **Budget en GiB** : `archives take-budget-gib GiB`

> Par défaut, `calewood-toolbox` est en **dry‑run**. Pour exécuter réellement : ajouter `--just-do-it`.

## Commandes

### 1) Prendre les N plus petits items

```bash
calewood-toolbox archives take-smallest N [OPTIONS]
```

Ce que fait la commande :

1. Appelle `GET /api/archive/list?status=...&sort=size_bytes&order=asc` (paginé, `per_page=200`)
2. Prend les **N premiers** items retournés (donc les plus petits)
3. Exécute `POST /api/archive/take/{id}` (ou affiche ce qui serait fait en dry‑run)
4. Optionnel : enchaîne `POST /api/archive/complete/{id}` avec `--complete`

Options (filtres côté API) :

- `--status uploaded` : statut ciblé (défaut : `uploaded`)
- `--cat CAT` / `--subcat SUBCAT` : filtre catégorie / sous‑catégorie (exact)
- `--q Q` : recherche
- `--complete` : enchaîne `complete` après `take` (attend 1 seconde entre les 2)
- `--qb-host NAME --add-to-qbit` : après un `take` réussi, télécharge le `.torrent` La‑Cale et l’ajoute dans qBittorrent (**started**, `skip_checking` activé)

Exemples :

```bash
# Voir ce qui serait pris (dry-run)
calewood-toolbox archives take-smallest 15

# Prendre réellement 15 items (avec complete)
calewood-toolbox --just-do-it archives take-smallest 15 --complete

# Cibler une catégorie précise
calewood-toolbox archives take-smallest 15 --cat "Vidéos" --subcat "Films"

# Prendre et ajouter dans qBittorrent (catégorie qBittorrent définie par instance, défaut: calewood)
calewood-toolbox --just-do-it archives take-smallest 15 --qb-host sd-183106 --add-to-qbit
```

### 2) Prendre jusqu’à un budget en GiB

```bash
calewood-toolbox archives take-budget-gib GiB [OPTIONS]
```

Ce que fait la commande :

1. Scanne `GET /api/archive/list?status=...&sort=size_bytes&order=asc` (paginé, `per_page=200`)
2. Construit une sélection en **additionnant** les tailles (`size_bytes`) jusqu’à **atteindre le budget**
3. Exécute `POST /api/archive/take/{id}` sur chaque item sélectionné (ou affiche en dry‑run)
4. Optionnel : enchaîne `POST /api/archive/complete/{id}` avec `--complete`

Options :

- `--status uploaded` (défaut : `uploaded`)
- `--cat` / `--subcat` / `--q`
- `--max-items N` : limite le nombre d’items pris (0 = illimité)
- `--max-pages-classic N` *(uniquement via `take budget-gib`, voir plus bas)* : limite le scan pagination (0 = toutes)
- `--complete`
- `--qb-host NAME --add-to-qbit` : après un `take` réussi, ajoute aussi dans qBittorrent (started + skip_checking)

Exemples :

```bash
# Sélectionner jusqu'à 150 GiB (dry-run)
calewood-toolbox archives take-budget-gib 150

# Exécuter réellement (take + complete)
calewood-toolbox --just-do-it archives take-budget-gib 150 --complete

# Ne scanner que quelques pages (accélère fortement si la liste est énorme)
calewood-toolbox archives take-budget-gib 150 --max-items 40

# Exécuter + ajouter dans qBittorrent
calewood-toolbox --just-do-it archives take-budget-gib 150 --qb-host sd-183106 --add-to-qbit
```

## Alias : `take budget-gib`

```bash
calewood-toolbox take budget-gib GiB [OPTIONS]
```

Cette commande est un **raccourci** pour l’archivage classique (elle ne touche pas au pré‑archivage) :

- source : `GET /api/archive/list`
- action : `POST /api/archive/take/{id}` (+ `complete` optionnel)
- tri : taille croissante

Options :

- `--classic-status uploaded` : statut (défaut : `uploaded`)
- `--cat` / `--subcat` / `--q`
- `--max-items N`
- `--max-pages-classic N` : limite le scan de pages (0 = toutes)
- `--complete-classic`
- `--qb-host NAME --add-to-qbit` : après un `take` réussi, ajoute aussi dans qBittorrent (started + skip_checking)

Exemples :

```bash
# Dry-run rapide (2 pages max)
calewood-toolbox take budget-gib 150 --max-pages-classic 2

# Exécuter réellement
calewood-toolbox --just-do-it take budget-gib 150 --complete-classic

# Exécuter + ajouter dans qBittorrent
calewood-toolbox --just-do-it take budget-gib 150 --qb-host sd-183106 --add-to-qbit
```

## Configuration qBittorrent : catégorie par instance

La catégorie qBittorrent utilisée est :

- `calewood` par défaut
- ou `category` si défini dans `QBIT_INSTANCES_JSON`

Exemple `.env` :

```bash
QBIT_INSTANCES_JSON='[
  {"name":"sd-183106","base_url":"https://qbittorrent.exemple","username":"user","password":"pass","category":"calewood"}
]'
```
