# Dépréciations

Ce fichier liste les commandes/options conservées **uniquement** pour compatibilité, mais qui sont considérées comme dépréciées.

## `--arbitre-*`

Toutes les options `--arbitre-*` sont **dépréciées** :

- Elles restent implémentées dans le code pour ne pas casser d’anciens scripts.
- Elles sont masquées de `--help` (utilisation de `argparse.SUPPRESS`).

Migration recommandée : utiliser les workflows Pré‑archivage (`/api/archive/pre-archivage/*`) et Fiches uploader (`/api/upload/pre-archivage/*`) selon le besoin.

