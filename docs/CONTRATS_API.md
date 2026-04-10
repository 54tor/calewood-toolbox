# Contrats API (référence)

Ce dossier sert de mémo “contrats” pour les endpoints utilisés par `calewood-toolbox`.

Le format est volontairement simple : **endpoint**, **méthode**, **query/body**, **réponse attendue** (structure).

## Authentification

- Header obligatoire : `Authorization: Bearer <token>`

## Format des réponses

### Succès

```json
{
  "success": true,
  "data": { }
}
```

### Liste paginée

```json
{
  "success": true,
  "data": [ ],
  "meta": { "total": 0, "page": 1, "per_page": 50, "has_more": false }
}
```

### Erreur

```json
{
  "success": false,
  "error": "Message",
  "code": 401
}
```

## Uploads (classique)

### GET `/api/upload/list`

Liste des uploads (paginé).

Query (GET) :

- `status` — filtre par statut, CSV accepté (ex: `new,selected,uploading`). Sans filtre : tous les statuts.
- `q` — recherche par nom
- `cat` — filtre catégorie
- `subcat` — filtre sous-catégorie *(si supporté par l’API)*
- `sort` — tri : `name`, `size_bytes`, `category`, `seeders`, `selected_at`, `uploaded_at`, `archived_at`
- `order` — `asc` / `desc`
- `per_page` — résultats par page (défaut 50, max 200)
- `p` — numéro de page

### POST `/api/upload/take/{id}`

Prend un upload (réservation / prise en charge).

Body :

- `{}` (vide)

### POST `/api/upload/abandon/{id}`

Abandonne un upload.

Body :

- `{}` (vide)

### GET `/api/upload/get/{id}`

Détail d’un upload.

## Torrents (recherche)

### GET `/api/torrent/list`

Recherche de torrents (paginé).

Query :

- `q` — recherche nom / hash (ex: `sharewood_hash`)
- `cat` / `subcat` / etc. selon API

### GET `/api/torrent/comment/{id}`

Récupère le commentaire d’un torrent.

### POST `/api/torrent/comment/{id}`

Met à jour le commentaire d’un torrent.

Body :

```json
{ "comment": "..." }
```

## Archivage classique (`/api/archive/*`)

### GET `/api/archive/list`

Liste d’archives (paginé).

Query :

- `status` — ex: `my-archives`, `my-archiving`, etc.
- `q`, `cat`, `subcat`, `seeders`, `min_size`, `max_size`, `sort`, `order`, `per_page`, `p`, `v1_only`

### GET `/api/archive/get/{id}`

Détail archive.

### POST `/api/archive/take/{id}`

Prendre une archive.

### POST `/api/archive/complete/{id}`

Marquer une archive comme complète.

## Pré‑archivage (Archiviste)

### GET `/api/archive/pre-archivage/list`

Sans filtre : items `selected` disponibles (tri/filtres côté API).

Query :

- `status` — ex: `my-pre-archiving`
- `q`, `cat`, `subcat`, `seeders`, `min_size`, `max_size`, `per_page`, `p`

### POST `/api/archive/pre-archivage/take/{id}`

`selected` → `pre_archiving`

### POST `/api/archive/pre-archivage/dl-done/{id}`

`pre_archiving` → `awaiting_fiche`

### POST `/api/archive/pre-archivage/confirm/{id}`

`post_archiving` → `done`

### POST `/api/archive/pre-archivage/abandon/{id}`

`pre_archiving`/`awaiting_fiche` → `selected`

### POST `/api/archive/pre-archivage/blast/{id}`

`pre_archiving`/`awaiting_fiche` → `new`

### GET `/api/archive/pre-archivage/torrent-file/{id}`

Télécharge le `.torrent` Sharewood (binaire).

## Pré‑archivage (Uploader / fiches)

### GET `/api/upload/pre-archivage/list`

Sans filtre : `awaiting_fiche`.

Query :

- `status` — ex: `my-fiches`, `my-completed`
- `q`, `cat`, `per_page`, `p`

### POST `/api/upload/pre-archivage/take/{id}`

Prendre une fiche.

### POST `/api/upload/pre-archivage/complete/{id}`

`awaiting_fiche` → `post_archiving`

Body :

```json
{ "url_lacale": "https://la-cale.space/..." }
```

