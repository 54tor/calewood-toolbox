# Référence API Calewood (utilisée par `calewood-toolbox`)

Ce document liste les endpoints Calewood consommés par ce projet, ainsi que les paramètres/contrats attendus.

Toutes les requêtes exigent :

- Header `Authorization: Bearer <token>`

## Formats de réponse

- Succès : `{ "success": true, "data": ..., "meta": ... }`
- Erreur : `{ "success": false, "error": "...", "code": 4xx/5xx }`

## Pagination standard

La plupart des `list` utilisent :

- `per_page` (1–200)
- `p` (page, à partir de 1)
- `meta.has_more` (bool)

## Endpoints

### Torrents (lecture)

- `GET /api/torrent/list?q=...`
  - Utilisation : retrouver un torrent via `sharewood_hash` (la recherche `q` matche aussi sur le nom).

### Uploads (legacy)

- `GET /api/upload/list?status=...&per_page=...&p=...`
- `POST /api/upload/take/{id}`
- `POST /api/upload/complete/{id}`
- `POST /api/upload/abandon/{id}`
- `POST /api/upload/blast/{id}`

#### Seedbox (uploads)

- `POST /api/upload/seedbox-check`
  - Body JSON : `{ "passphrase": "..." }` (**obligatoire**)
  - Effet : met à jour `seedbox_progress` côté API pour vos torrents en `uploading`.

### Archivage legacy

- `GET /api/archive/list?...`
  - Filtres supportés (selon l’API) : `status`, `q`, `cat`, `subcat`, `seeders`, `min_size`, `max_size`, `sort`, `order`, `v1_only`
- `POST /api/archive/take/{id}`
- `POST /api/archive/complete/{id}`
- `POST /api/archive/revert-done/{id}`

#### Seedbox (archives legacy)

- `POST /api/archive/seedbox-check`
  - Body JSON : `{ "passphrase": "..." }` (**obligatoire**)
  - Effet : met à jour `seedbox_progress` côté API pour vos torrents en cours d’archivage.

### Pré‑archivage (Archiviste)

- `GET /api/archive/pre-archivage/list?...`
  - Sans `status` : pool `selected` disponible (tri/seeders gérés côté API).
  - `status=my-pre-archiving` : vos torrents (`pre_archiving`, `awaiting_fiche`, `post_archiving`).
  - Filtres : `status`, `q`, `cat`, `subcat`, `seeders`, `min_size`, `max_size`, pagination standard.
- `POST /api/archive/pre-archivage/take/{id}` (selected → pre_archiving)
- `POST /api/archive/pre-archivage/dl-done/{id}` (pre_archiving → awaiting_fiche)
- `POST /api/archive/pre-archivage/confirm/{id}` (post_archiving → done)
- `POST /api/archive/pre-archivage/abandon/{id}` (pre_archiving/awaiting_fiche → selected)
- `POST /api/archive/pre-archivage/blast/{id}` (pre_archiving/awaiting_fiche → new)
- `GET /api/archive/pre-archivage/torrent-file/{id}`
  - Retour : binaire `.torrent` Sharewood (nécessite que l’item vous appartienne côté API).

### Pré‑archivage (Uploader / fiches)

- `GET /api/upload/pre-archivage/list?...`
  - Sans `status` : toutes les fiches en attente (`awaiting_fiche`).
  - `status=my-fiches` : vos fiches en cours (awaiting_fiche, uploader_id = vous).
  - `status=my-completed` : vos fiches terminées (post_archiving + done).
  - Filtres : `status`, `q`, `cat`, pagination standard.
- `POST /api/upload/pre-archivage/take/{id}`
- `POST /api/upload/pre-archivage/complete/{id}`
  - Body JSON : `{ "url_lacale": "https://la-cale.space/..." }`
- `POST /api/upload/pre-archivage/abandon/{id}`
- `POST /api/upload/pre-archivage/blast/{id}`
  - Body JSON : `{ "reason": "..." }` (**obligatoire**)
- `POST /api/upload/pre-archivage/scrape/{id}`
- `POST /api/upload/pre-archivage/search-media/{id}`
- `POST /api/upload/pre-archivage/generate-prez/{id}`
- `POST /api/upload/pre-archivage/verify-prez/{id}`
- `POST /api/upload/pre-archivage/post-lacale/{id}`
  - Body JSON : `{ "passphrase": "..." }` (**obligatoire**)

