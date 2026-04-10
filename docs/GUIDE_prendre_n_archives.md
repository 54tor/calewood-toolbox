# Guide : prendre N archives (les plus petits)

Objectif : prendre **N** items à archiver (par défaut `status=uploaded`), triés par **taille croissante**.

## Commande

```bash
calewood-toolbox archives take-smallest N [OPTIONS]
```

## Exemples

```bash
# Dry-run : simuler la prise de 15 items
calewood-toolbox archives take-smallest 15

# Exécuter réellement (take)
calewood-toolbox --just-do-it archives take-smallest 15

# Exécuter + enchaîner complete
calewood-toolbox --just-do-it archives take-smallest 15 --complete
```

## Filtres utiles

- `--status uploaded` (défaut : `uploaded`)
- `--cat CAT` / `--subcat SUBCAT`
- `--q Q`

## Obtenir les liens La‑Cale (stdout) / ouvrir si desktop

Après un `take` réussi, tu peux récupérer les liens La‑Cale correspondant aux items pris :

```bash
# Imprimer sur stdout (toujours)
calewood-toolbox --just-do-it archives take-smallest 15 --print-lacale-download-urls

# Tenter d'ouvrir via xdg-open (uniquement si desktop), et imprimer aussi
calewood-toolbox --just-do-it archives take-smallest 15 --open-lacale-download
```

Réglages :

- `--open-batch N` (défaut 10)
- `--open-sleep-seconds S` (défaut 1)

