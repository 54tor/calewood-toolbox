# calewood-toolbox

Boîte à outils CLI pour automatiser des workflows entre une instance Calewood et une ou plusieurs instances qBittorrent.

Ce dépôt ne contient **aucun identifiant** ni **endpoint privé**. Tout se configure via variables d’environnement à l’exécution.

## Contenu

- CLI Python : `calewood-toolbox`
- Docs :
  - `docs/CONTRATS_API.md` (contrats / endpoints utilisés)
  - `docs/SCENARIO-prendre-uploads-selected.md`

## Exécution (Docker)

Image recommandée : `sat0r/calewood-toolbox:latest`

Exécution (image Docker Hub) :

```bash
docker run --rm -it \
  --env-file .env \
  sat0r/calewood-toolbox:latest --help
```

Alternative : injection directe de variables d’environnement :

```bash
docker run --rm -it \
  -e CALEWOOD_BASE_URL="https://calewood.n0flow.io/api" \
  -e CALEWOOD_TOKEN="..." \
  -e QBIT_INSTANCES_JSON='[{"name":"box","base_url":"http://qb:8080","username":"user","password":"pass"}]' \
  sat0r/calewood-toolbox:latest --help
```

Alternative : monter un fichier `.env` dans le conteneur :

```bash
docker run --rm -it \
  -v "$PWD/.env:/app/.env:ro" \
  sat0r/calewood-toolbox:latest --help
```

## Configuration

### Calewood

- `CALEWOOD_BASE_URL` (défaut: `https://calewood.n0flow.io/api`)
- `CALEWOOD_TOKEN` (Bearer token)
- `CALEWOOD_SEEDBOX_PASSPHRASE` (requis pour les commandes qui déclenchent `*/seedbox-check`)

Astuce : tu peux copier `.env.example` vers `.env` et exporter ces variables dans ton shell.

Le CLI charge automatiquement un fichier `.env` s’il est présent dans le répertoire courant.

### Instances qBittorrent

Définir des instances via JSON :

```bash
export QBIT_INSTANCES_JSON='[
  {"name":"box","base_url":"http://qb:8080","username":"user","password":"pass","mirror_category":"calewood-mirror"}
]'
```

Puis exécute avec :

```bash
calewood-toolbox qbit dl-queue --qb-host box
```

Champs optionnels par instance :

- `mirror_category` : catégorie utilisée par `qbit mirror` à l'ajout dans la destination
- `category_upload` : catégorie utilisée par les prises de fichiers Sharewood vers qBittorrent

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
- `archives take-smallest N` : prend les N plus petits items (par défaut `status=uploaded`).
- `archives take-budget-gib GiB` : prend jusqu'à un budget (GiB), triés par taille croissante.

#### Take (archivage classique)

- `take budget-gib GiB` : alias "budget" sur l'archivage classique (`/api/archive/list`), tri par taille croissante.

#### Pré‑archivage (Archiviste)

- `prearchivage take-budget-gib GiB` : prend jusqu'à un budget (GiB) dans le pool pré‑archivage (tri taille croissante).

#### qBittorrent

- `qbit get --qb-host NAME HASH` : récupère un torrent par hash.
- `qbit dl-queue --qb-host NAME` : stats file de téléchargement.
- `qbit mirror --src SRC --dst DST [--dst DST2 ...]` : copie les torrents présents dans la source mais absents dans une ou plusieurs destinations.
  - défauts prudents : `--limit 50`, `--batch-size 5`, `--batch-sleep-seconds 2`
  - `--batch-size N` / `--batch-sleep-seconds S` : lisse les ajouts par lots pour éviter de saturer la destination
- `torrents q Q` : recherche via `GET /api/torrent/list?q=...` (nom ou `sharewood_hash`).

### Scénarios (docs)

- `docs/CONTRATS_API.md`
- `docs/SCENARIO-prendre-uploads-selected.md`
- `docs/SCENARIO-archives-prendre-n-ou-budget.md`
- `docs/SCENARIO-prearchivage-prendre-budget.md`
- `docs/GUIDE-prendre-budget-gib.md`
- `docs/GUIDE-prendre-n-archives.md`

### Dépréciations

`DEPRECATED.md` liste les tâches/options qui ont existé à un moment (mémoire + historique), sans forcément être encore exposées.

### Liste des commandes

Le `--help` est la référence (aide en étages). Les commandes principales :

- `uploads take-selected`
- `uploads count-done-mine`
- `fiches take-awaiting`
- `archives verify-my`
- `archives take-smallest`
- `archives take-budget-gib`
- `prearchivage take-budget-gib`
- `take budget-gib`
- `qbit get`
- `qbit dl-queue`

## Licence

GPL-3.0

## Annexe : installation

### Docker (build local)

```bash
docker build -t calewood-toolbox .
```

Puis exécuter l'image locale buildée :

```bash
docker run --rm -it \
  --env-file .env \
  calewood-toolbox --help
```

### Python (local)

```bash
python -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e .
calewood-toolbox --help
```
