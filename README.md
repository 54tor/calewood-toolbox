# calewood-toolbox

Boîte à outils CLI (anonymisée) pour automatiser des workflows entre une instance Calewood et une ou plusieurs instances qBittorrent.

Ce dépôt ne contient **aucun identifiant** ni **endpoint privé**. Tout se configure via variables d’environnement à l’exécution.

## Contenu

- CLI Python : `calewood-toolbox`
- Docs :
  - `docs/API_CONTRACTS.md` (contrats / endpoints utilisés)
  - `docs/SCENARIO_prendre_uploads_selected.md` (exemple de scénario)

## Docker (recommandé)

Image recommandée : `sat0r/calewood-toolbox:latest`

Build :

```bash
docker build -t calewood-toolbox .
```

Exécution (exemple, image locale) :

```bash
docker run --rm -it \
  -e CALEWOOD_BASE_URL="https://calewood.n0flow.io/api" \
  -e CALEWOOD_TOKEN="..." \
  -e QBIT_INSTANCES_JSON='[{"name":"box","base_url":"http://qb:8080","username":"user","password":"pass"}]' \
  calewood-toolbox --help
```

Exécution (exemple, image Docker Hub) :

```bash
docker run --rm -it \
  -e CALEWOOD_BASE_URL="https://calewood.n0flow.io/api" \
  -e CALEWOOD_TOKEN="..." \
  -e QBIT_INSTANCES_JSON='[{"name":"box","base_url":"http://qb:8080","username":"user","password":"pass"}]' \
  sat0r/calewood-toolbox --help
```

Astuce : si tu utilises un `.env`, tu peux le monter et laisser le CLI le charger :

```bash
docker run --rm -it \
  -v "$PWD/.env:/app/.env:ro" \
  sat0r/calewood-toolbox --help
```

Alternative : tu peux aussi laisser Docker injecter les variables :

```bash
docker run --rm -it \
  --env-file .env \
  sat0r/calewood-toolbox --help
```

## Configuration

### Calewood

- `CALEWOOD_BASE_URL` (défaut: `https://calewood.n0flow.io/api`)
- `CALEWOOD_TOKEN` (Bearer token)
- `CALEWOOD_SEEDBOX_PASSPHRASE` (requis pour les commandes qui déclenchent `*/seedbox-check`)

Astuce : tu peux copier `.env.example` vers `.env` et exporter ces variables dans ton shell.

Le CLI charge automatiquement un fichier `.env` s’il est présent dans le répertoire courant.

### Instances qBittorrent

Provide instances via JSON:

```bash
export QBIT_INSTANCES_JSON='[
  {"name":"box","base_url":"http://qb:8080","username":"user","password":"pass"}
]'
```

Puis exécute avec :

```bash
calewood-toolbox qbit dl-queue --qb-host box
```

## Commandes

Note : le CLI est en **dry-run par défaut**. Ajoute `--just-do-it` pour exécuter vraiment.

Le CLI est organisé en **sous‑commandes** (aide “en étages”, uniquement les options compatibles).

### Général

- `-h` : aide complète.
- `--verbose` : logs détaillés.
- `--json` : sortie JSON (quand supporté par la commande).

### Sous‑commandes

#### Uploads

- `uploads take-selected` : liste `/api/upload/list?status=selected` et prend (`POST /api/upload/take/{id}`) les uploads qui matchent.
  - filtres côté API : `--cat`, `--subcat`, `--q`, `--sort`, `--order`
  - filtres côté Python : `--name-regex` (inclure) / `--exclude-regex` (exclure)
  - `--limit` : limite le nombre de prises

Exemple :

```bash
calewood-toolbox uploads take-selected \
  --cat "ebook" \
  --q "Asimov" \
  --sort size_bytes --order desc \
  --exclude-regex "tome\\s*1" \
  --limit 10 \
  --just-do-it --verbose
```

#### Archives (classique /api/archive)

- `archives verify-my --qb-host NAME` : compare `my-archives` vs qBittorrent et affiche les manquants.

#### Pré‑archivage (Archiviste)

- `prearchivage take-smallest N` : prend les N plus petits items disponibles et télécharge les `.torrent`.

#### qBittorrent

- `qbit get --qb-host NAME HASH` : récupère un torrent par hash.
- `qbit dl-queue --qb-host NAME` : stats file de téléchargement.

### Dépréciations

`DEPRECATED.md` liste les tâches/options qui ont existé à un moment (mémoire + historique), sans forcément être encore exposées.

### Calewood legacy (recherche / listing)

- `--calewood-list PER_PAGE` : test d’accès API Calewood.
- `--calewood-torrent-q Q` : recherche via `GET /api/torrent/list?q=...` (paginé).
- `--calewood-find-sharewood-hash HASH` : trouve un torrent Calewood par `sharewood_hash` (via `/api/torrent/list?q=`).
- `--calewood-find-lacale-hash HASH` : trouve un legacy archive par `lacale_hash` (via `/api/archive/list`).

### Archivage classique (/api/archive/*)

- `--calewood-archive-uploaded` : liste les items `status=uploaded` (à prendre).
- `--calewood-archive-take-uploaded` : `POST /api/archive/take/{id}` sur tous les `uploaded` (respecte `--limit`).
- `--calewood-archive-take-uploaded-to-qbit` : take + téléchargement `.torrent` La‑Cale + ajout sur `--qb-host`.
- `--verify-my-archives-in-qbit` : compare `my-archives` vs qBittorrent (`--qb-host`), affiche les manquants.
- `--open-lacale-download` : ouvre les liens La‑Cale pour les manquants (utilisé avec `--verify-my-archives-in-qbit`).

### Pré‑archivage (Archiviste) (/api/archive/pre-archivage/*)

- `--list-archive-prearchivage` : liste le pool pré‑archivage (filtrable via `--prearchivage-status`).
- `--prearchivage-take ID` / `--prearchivage-abandon ID` / `--prearchivage-confirm ID` / `--prearchivage-blast ID` : actions unitaires.
- `--prearchivage-download-my-torrents` : télécharge mes `.torrent` Sharewood (status `my-pre-archiving`), option `--prearchivage-add-to-qbit`.
- `--prearchivage-download-my-awaiting-fiche-torrents` : variante “awaiting_fiche” uniquement.
- `--prearchivage-verify-my-awaiting-fiche-100` : vérifie que mes `awaiting_fiche` sont à 100% sur `--qb-host`.
- `--prearchivage-redl-my-awaiting-fiche-not-complete` : retélécharge et ré‑ajoute dans qBittorrent les non-100%.
- `--prearchivage-confirm-my-post-archiving-100` : confirme mes `post_archiving` si présents à 100% sur `--qb-host` (sinon ouvre le download).

### Pré‑archivage (Uploader / fiches) (/api/upload/pre-archivage/*)

- `--fiche-list [STATUS]` : liste les fiches (par défaut `awaiting_fiche`).
- `--fiche-take ID` / `--fiche-complete ID --fiche-url-lacale URL` / `--fiche-abandon ID` / `--fiche-blast ID --fiche-reason TEXT` : actions unitaires.
- `--fiche-take-awaiting-category CAT` : take en masse des fiches `awaiting_fiche` pour `category==CAT` (filtre API `cat=...` + post-filtre regex optionnel `--fiche-take-name-regex`).
  - Filtre : `--fiche-take-subcat "Films X"` pour restreindre à une sous-catégorie exacte.
  - Sortie : tableau `ID STATUS CAT SUBCAT NAME HASH` par défaut (utilise `--json` pour JSONL).

### qBittorrent (outil / maintenance) (nécessite souvent `--qb-host`)

- `--qbit-get-hash HASH` : affiche un torrent qBittorrent.
- `--qbit-dl-queue` / `--qbit-downloading-gib` : stats de file d’attente / backlog.
- `--qbit-cycle-stop-slow-downloads` : round-robin des DL pour garder un nombre de slots actifs.
- `--qbit-add-tracker URL` / `--qbit-remove-tracker URL` : gestion trackers (avec filtres).
- `--qbit-orphan-non-lacale-twins` : liste les torrents non‑La‑Cale sans jumeau La‑Cale (nom identique), hors `cross-seed` + hors items Calewood en cours.
- `--qbit-orphan-non-lacale-twins-delete` : supprime (torrent + fichiers) les orphelins listés (par défaut `--limit 1`).

### Migration (qBittorrent)

- `--migrate-sharewood-to-calewood` : migration Sharewood ↔ La‑Cale (move data + re-add skip_checking + tags/catégories).
- `--migrate-from-prefix` / `--migrate-to-prefix` : mapping des chemins.

### Fichiers / FS

- `--fs-orphans ROOT` : compare FS vs qBittorrent (multi-instances possibles), sort les chemins orphelins.
- `--fs-ignore PATH` / `--path-map FROM=TO` / `--managed-ignore-prefix PREFIX` : réglages de scan.

## Exemples rapides

- Aide :
  - `calewood-toolbox --help`

- File d’attente / backlog qBittorrent :
  - `calewood-toolbox qbit dl-queue --qb-host box`

- Archivage classique : éléments disponibles à prendre (`status=uploaded`) :
  - `calewood-toolbox --calewood-archive-uploaded`

- Prendre les `uploaded` (classique) et les ajouter à qBittorrent (nécessite `--qb-host`) :
  - `calewood-toolbox --qb-host box --calewood-archive-take-uploaded-to-qbit --just-do-it --verbose`

## Annexe : exécution locale

```bash
python -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e .
calewood-toolbox --help
```

## Licence

GPL-3.0
