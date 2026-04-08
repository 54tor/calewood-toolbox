# Dépréciations

Ce fichier liste les commandes/options conservées **uniquement** pour compatibilité, mais qui sont considérées comme dépréciées.

## `--arbitre-*`

Toutes les options `--arbitre-*` sont **dépréciées** :

- Elles restent implémentées dans le code pour ne pas casser d’anciens scripts.
- Elles sont masquées de `--help` (utilisation de `argparse.SUPPRESS`).

Migration recommandée : utiliser les workflows Pré‑archivage (`/api/archive/pre-archivage/*`) et Fiches uploader (`/api/upload/pre-archivage/*`) selon le besoin.

## `--shutup-take-my-storage`

Cette commande est **dépréciée** et masquée de `--help`.

Raison : trop “large” (take massif) et trop risqué pour être gardé en surface.

## `--abandon-low-seeders`

Cette commande est **dépréciée** et masquée de `--help`.

Raison : action destructive (abandon) basée sur des heuristiques (seeders), préférable en script ponctuel.

## `--calewood-upload-take-low-seeders`

Cette commande est **dépréciée** et masquée de `--help`.

Raison : commande “listing” trop spécifique (seeders<=1) qui a été absorbée par d’autres workflows plus ciblés.

## `--abandon-stalled-zero`

Cette commande est **dépréciée** et masquée de `--help`.

Raison : abandon automatique basé sur un état “stall à 0%”, trop spécifique/risqué pour rester en surface.

## qBittorrent “stalled/blast” (`--qbit-stalled-*`)

Les commandes suivantes sont **dépréciées** et masquées de `--help` :

- `--qbit-stalled-zero`
- `--qbit-stalled-zero-blast`
- `--qbit-stalled-zero-delete`
- `--qbit-stalled-0pct-6h-prearchivage-blast`
- `--qbit-stalled-4h-prearchivage-blast`

Raison : actions destructives (blast/suppression) basées sur des heuristiques de débit/temps, à garder pour usage ponctuel.
