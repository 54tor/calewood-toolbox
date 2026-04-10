# Guide : prendre un budget (GiB) en archivage classique

Objectif : prendre des items **disponibles** à archiver (par défaut `status=uploaded`) jusqu’à un budget en **GiB**, triés par **taille croissante**.

## Dry‑run vs exécution

- Par défaut : **dry‑run** (aucun `POST` n’est exécuté)
- Pour exécuter : ajouter `--just-do-it`

## Option 1 — via `archives take-budget-gib`

```bash
calewood-toolbox archives take-budget-gib GiB [OPTIONS]
```

Exemples :

```bash
# Dry-run : simuler la prise de 150 GiB
calewood-toolbox archives take-budget-gib 150

# Exécuter réellement (take)
calewood-toolbox --just-do-it archives take-budget-gib 150

# Exécuter + enchaîner complete
calewood-toolbox --just-do-it archives take-budget-gib 150 --complete
```

Filtres utiles :

- `--status uploaded` (défaut : `uploaded`)
- `--cat CAT` / `--subcat SUBCAT`
- `--q Q`
- `--max-items N` (limite d’items)

## Option 2 — via `take budget-gib` (raccourci)

```bash
calewood-toolbox take budget-gib GiB [OPTIONS]
```

Différence principale :

- ajoute `--max-pages-classic N` pour limiter le scan pagination (accélère si la liste est très grosse)

Exemples :

```bash
# Dry-run plus rapide (2 pages max)
calewood-toolbox take budget-gib 150 --max-pages-classic 2

# Exécuter réellement
calewood-toolbox --just-do-it take budget-gib 150
```

## Obtenir les liens La‑Cale (stdout) / ouvrir si desktop

Après un `take` réussi, tu peux récupérer les liens La‑Cale correspondant aux items pris :

```bash
# Imprimer sur stdout (toujours)
calewood-toolbox --just-do-it take budget-gib 150 --print-lacale-download-urls

# Tenter d'ouvrir via xdg-open (uniquement si desktop), et imprimer aussi
calewood-toolbox --just-do-it take budget-gib 150 --open-lacale-download
```

Réglages :

- `--open-batch N` (défaut 10)
- `--open-sleep-seconds S` (défaut 1)

## (Optionnel) envoyer le .torrent Sharewood vers un client torrent

Uniquement si tu as un qBittorrent configuré dans `QBIT_INSTANCES_JSON` :

```bash
calewood-toolbox --just-do-it take budget-gib 150 \
  --qb-host sd-183106 \
  --add-sharewood-to-qbit
```

La catégorie qBittorrent utilisée est :

- `calewood-upload` par défaut
- ou `category_upload` si défini dans `QBIT_INSTANCES_JSON` pour l’instance

