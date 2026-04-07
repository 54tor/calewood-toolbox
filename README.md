# calewood-toolbox

Boîte à outils CLI (anonymisée) pour automatiser des workflows entre une instance Calewood et une ou plusieurs instances qBittorrent.

Ce dépôt ne contient **aucun identifiant** ni **endpoint privé**. Tout se configure via variables d’environnement à l’exécution.

## Contenu

- CLI Python : `calewood-toolbox` (entrée vers `calewood_qbit_sync`)
- Scripts Bash :
  - `check_qbit_vs_calewood.sh`
  - `check_archiviste.sh`

## Installation (local)

```bash
python -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e .
calewood-toolbox -h
```

## Configuration

### Calewood

- `CALEWOOD_BASE_URL` (example: `https://calewood.example`)
- `CALEWOOD_TOKEN` (Bearer token)

### Instances qBittorrent

Provide instances via JSON:

```bash
export QBIT_INSTANCES_JSON='[
  {"name":"box","base_url":"http://qb:8080","username":"user","password":"pass"}
]'
```

Puis exécute avec :

```bash
calewood-toolbox --qb-host box ...
```

## Exemples rapides

- Aide :
  - `calewood-toolbox -h`

- File d’attente / backlog qBittorrent :
  - `calewood-toolbox --qb-host box --qbit-dl-queue`

- Archivage legacy : éléments disponibles à prendre (`status=uploaded`) :
  - `calewood-toolbox --calewood-archive-uploaded`

- Prendre les `uploaded` (legacy) et les ajouter à qBittorrent (nécessite `--qb-host`) :
  - `calewood-toolbox --qb-host box --calewood-archive-take-uploaded-to-qbit --no-dry-run --verbose`

- Planche contact (thumbsheet) à partir d’une vidéo locale :
  - `calewood-toolbox --thumbsheet ./video.mp4 --thumbsheet-out ./thumbsheet.png`

## Docker

Build:

```bash
docker build -t calewood-toolbox .
```

Exécution (exemple) :

```bash
docker run --rm -it \
  -e CALEWOOD_BASE_URL="https://calewood.example" \
  -e CALEWOOD_TOKEN="..." \
  -e QBIT_INSTANCES_JSON='[{"name":"box","base_url":"http://qb:8080","username":"user","password":"pass"}]' \
  calewood-toolbox -h
```

## Anonymisation

- `calewood_qbit_sync/config.py` contient uniquement des placeholders et lit la configuration via l’environnement.
- Ne commit jamais de secrets dans ce dépôt.

## Licence

GPL-3.0
