from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from . import config
from .calewood import CalewoodClient


def _env(name: str, default: str) -> str:
    import os

    v = os.environ.get(name, default)
    return v if v != "" else default


def _print_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
    widths = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(c))
    print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    print("  ".join(("-" * widths[i]) for i in range(len(headers))))
    for r in rows:
        print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))))


def _fmt_gib(nbytes: int) -> str:
    try:
        v = int(nbytes)
    except Exception:  # noqa: BLE001
        v = 0
    return f"{(v / (1024**3)):.2f} GiB"


def _has_desktop() -> bool:
    import os
    import shutil

    if not shutil.which("xdg-open"):
        return False
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _open_urls(urls: list[str], *, batch: int = 10, sleep_seconds: int = 1) -> int:
    """
    Affiche toujours les URLs (stdout).
    Ouvre via `xdg-open` uniquement si un environnement desktop est détecté.
    Retourne le nombre d'URLs réellement ouvertes.
    """
    urls = [str(u).strip() for u in (urls or []) if str(u).strip()]
    if not urls:
        return 0
    for u in urls:
        print(u)
    if not _has_desktop():
        return 0
    opened = 0
    for i, url in enumerate(urls, start=1):
        try:
            subprocess.Popen(["xdg-open", url])  # noqa: S603,S607
            opened += 1
        except Exception:
            pass
        if batch > 0 and i % batch == 0:
            time.sleep(max(0, int(sleep_seconds)))
    return opened


def _print_urls(urls: list[str]) -> None:
    urls = [str(u).strip() for u in (urls or []) if str(u).strip()]
    for u in urls:
        print(u)


def _iter_archives(
    calewood: CalewoodClient,
    *,
    status: str,
    q: str | None,
    cat: str | None,
    subcat: str | None,
    max_pages: int = 0,
) -> list[dict]:
    """Retourne les items (paged) triés côté API par taille croissante."""
    per_page = 200
    page = 1
    items_all: list[dict] = []
    while True:
        resp = calewood.list_archives(
            status=status,
            q=q,
            cat=cat,
            subcat=subcat,
            sort="size_bytes",
            order="asc",
            p=page,
            per_page=per_page,
            v1_only=0,
        )
        if not isinstance(resp, dict) or not resp.get("success"):
            raise RuntimeError(f"Calewood archive list failed at page {page}: {resp}")
        batch = resp.get("data")
        meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
        has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
        if isinstance(batch, list):
            for it in batch:
                if isinstance(it, dict):
                    items_all.append(it)
        if not has_more:
            break
        page += 1
        if max_pages > 0 and page > max_pages:
            break
    return items_all


def _size_bytes(it: dict) -> int:
    try:
        return int(it.get("size_bytes") or 0)
    except Exception:  # noqa: BLE001
        return 0


def _select_smallest(items_sorted: list[dict], *, n: int) -> list[dict]:
    if n <= 0:
        return []
    return items_sorted[:n]


def _select_budget(items_sorted: list[dict], *, budget_gib: int, max_items: int = 0) -> tuple[list[dict], int]:
    if budget_gib <= 0:
        return [], 0
    budget_bytes = budget_gib * (1024**3)
    selected: list[dict] = []
    total_bytes = 0
    for it in items_sorted:
        sz = _size_bytes(it)
        if sz <= 0:
            continue
        if total_bytes + sz > budget_bytes:
            continue
        selected.append(it)
        total_bytes += sz
        if max_items > 0 and len(selected) >= max_items:
            break
    return selected, total_bytes


def _lacale_urls(items: list[dict]) -> list[str]:
    urls: list[str] = []
    for it in items:
        h = str(it.get("lacale_hash") or "").strip().lower()
        if h:
            urls.append(f"https://la-cale.space/api/torrents/download/{h}")
    return urls


def _maybe_print_and_open_urls(
    urls: list[str],
    *,
    print_urls: bool,
    open_urls: bool,
    batch: int,
    sleep_seconds: int,
    dry_run: bool,
) -> None:
    if not urls:
        return
    if print_urls:
        _print_urls(urls)
    if open_urls and not dry_run:
        opened = _open_urls(urls, batch=batch, sleep_seconds=sleep_seconds)
        print(f"opened={opened} urls={len(urls)}", file=sys.stderr)


def _take_archive(calewood: CalewoodClient, archive_id: int, *, complete: bool) -> None:
    calewood.take_archive(str(int(archive_id)))
    if complete:
        time.sleep(1)
        calewood.complete_archive(str(int(archive_id)))


def _qbit_from_instance(name: str):
    from .qbit import QbitClient

    n = (name or "").strip().lower()
    for inst in getattr(config, "QBIT_INSTANCES", []):
        if not isinstance(inst, dict):
            continue
        if str(inst.get("name", "")).strip().lower() != n:
            continue
        base_url = str(inst.get("base_url", "")).strip()
        username = str(inst.get("username", "")).strip()
        password = str(inst.get("password", "")).strip()
        if not base_url or not username or not password:
            raise RuntimeError(f"Instance qBittorrent incomplète: {name!r}")
        return QbitClient(base_url=base_url, username=username, password=password)
    raise RuntimeError(f"Instance qBittorrent inconnue: {name!r}")


def _qbit_from_instance_with_upload_category(name: str):
    qb = _qbit_from_instance(name)
    n = (name or "").strip().lower()
    for inst in getattr(config, "QBIT_INSTANCES", []):
        if not isinstance(inst, dict):
            continue
        if str(inst.get("name", "")).strip().lower() != n:
            continue
        cat = str(inst.get("category_upload") or "").strip()
        return qb, (cat or "calewood-upload")
    return qb, "calewood-upload"


def _qbit_instance_category(name: str, field: str, default: str) -> str:
    n = (name or "").strip().lower()
    for inst in getattr(config, "QBIT_INSTANCES", []):
        if not isinstance(inst, dict):
            continue
        if str(inst.get("name", "")).strip().lower() != n:
            continue
        cat = str(inst.get(field) or "").strip()
        return cat or default
    return default


def _calewood_client() -> CalewoodClient:
    token = _env("CALEWOOD_TOKEN", config.CALEWOOD_TOKEN).strip()
    if not token:
        raise RuntimeError(
            "CALEWOOD_TOKEN manquant. Fournissez-le via `.env` (local) ou `--env-file .env` (Docker)."
        )
    return CalewoodClient(
        base_url=_env("CALEWOOD_BASE_URL", config.CALEWOOD_BASE_URL),
        token=token,
    )


def main(argv: list[str] | None = None) -> int:
    """
    CLI : sous-commandes pour une aide "en étages" (uniquement les options compatibles).
    """
    argv = argv if argv is not None else sys.argv[1:]

    parser = argparse.ArgumentParser(prog="calewood-toolbox")
    parser.set_defaults(dry_run=True)
    dry_group = parser.add_mutually_exclusive_group(required=False)
    dry_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Mode dry-run (par défaut) : n'exécute aucune action modifiant l'état ; affiche seulement ce qui serait fait.",
    )
    dry_group.add_argument(
        "--just-do-it",
        dest="dry_run",
        action="store_false",
        help="Désactive le dry-run et exécute les actions modifiant l’état.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Sortie verbeuse (diagnostics).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Quand applicable, affiche en JSON (indenté) au lieu d'un tableau lisible.",
    )
    parser.add_argument(
        "--jsonl",
        action="store_true",
        help="Avec `--json`, affiche en JSONL (1 objet JSON par ligne) au lieu du JSON indenté.",
    )
    parser.add_argument(
        "--seedbox-passphrase",
        type=str,
        default="",
        metavar="TEXT",
        help="Passphrase pour les endpoints Calewood `seedbox-check` (peut aussi être définie via `CALEWOOD_SEEDBOX_PASSPHRASE`).",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    # take (classic)
    take = sub.add_parser("take", help="Prises (archivage classique).")
    tsub = take.add_subparsers(dest="take_cmd", required=True)
    tmix = tsub.add_parser(
        "budget-gib",
        help="Prend jusqu'à un budget (GiB) via l'archivage classique, triés par taille croissante.",
    )
    tmix.add_argument("gib", type=int, metavar="GiB", help="Budget total en GiB (arrondi inférieur).")
    tmix.add_argument(
        "--classic-status",
        default="uploaded",
        help="Filtre `status` pour `/api/archive/list` (défaut: uploaded).",
    )
    tmix.add_argument("--q", default="", help="Filtre `q` côté API (recherche).")
    tmix.add_argument("--cat", default="", help="Filtre `cat` côté API.")
    tmix.add_argument("--subcat", default="", help="Filtre `subcat` côté API.")
    tmix.add_argument(
        "--max-items",
        type=int,
        default=0,
        metavar="N",
        help="Nombre maximum d'items à prendre (0 = illimité).",
    )
    tmix.add_argument(
        "--complete-classic",
        action="store_true",
        help="Après `archive/take`, enchaîne aussi `POST /api/archive/complete/{id}`.",
    )
    tmix.add_argument(
        "--max-pages-classic",
        type=int,
        default=0,
        metavar="N",
        help="Limite le nombre de pages scannées côté archivage classique (0 = toutes).",
    )
    tmix.add_argument(
        "--open-lacale-download",
        action="store_true",
        help="Après un take réussi, ouvre le lien La‑Cale de téléchargement (https://la-cale.space/api/torrents/download/{lacale_hash}).",
    )
    tmix.add_argument(
        "--print-lacale-download-urls",
        action="store_true",
        help="Affiche sur stdout les URLs de téléchargement La‑Cale des items sélectionnés (sans ouverture navigateur).",
    )
    tmix.add_argument(
        "--open-batch",
        type=int,
        default=10,
        metavar="N",
        help="Ouvre au maximum N liens à la fois (défaut: 10).",
    )
    tmix.add_argument(
        "--open-sleep-seconds",
        type=int,
        default=1,
        metavar="S",
        help="Pause (secondes) entre chaque batch d'ouvertures (défaut: 1).",
    )
    tmix.add_argument("--qb-host", default="", help="Alias qBittorrent (optionnel).")
    tmix.add_argument(
        "--add-sharewood-to-qbit",
        action="store_true",
        help="Après un take réussi, télécharge le .torrent Sharewood et l'ajoute dans qBittorrent (catégorie par instance `category_upload`, défaut: calewood-upload).",
    )

    # qbit
    qbit = sub.add_parser("qbit", help="Commandes qBittorrent.")
    qsub = qbit.add_subparsers(dest="qbit_cmd", required=True)
    qget = qsub.add_parser("get", help="Récupère un torrent par hash.")
    qget.add_argument("--qb-host", required=True, help="Alias d'instance qBittorrent (name).")
    qget.add_argument("hash", metavar="HASH", help="Hash qBittorrent (infohash).")

    qqueue = qsub.add_parser("dl-queue", help="Statistiques de file de téléchargement.")
    qqueue.add_argument("--qb-host", required=True, help="Alias d'instance qBittorrent (name).")
    qlist = qsub.add_parser("list", help="Liste tous les torrents d'une instance qBittorrent.")
    qlist.add_argument("--qb-host", required=True, help="Alias d'instance qBittorrent (name).")
    qlist.add_argument(
        "--category",
        default="",
        help="Filtre par catégorie exacte (optionnel).",
    )
    qlist.add_argument(
        "--limit",
        type=int,
        default=0,
        metavar="N",
        help="Limite le nombre de torrents affichés (0 = illimité).",
    )
    qlist.add_argument(
        "--only-state",
        default="",
        help="Filtre local par état exact (optionnel).",
    )
    qdiff = qsub.add_parser("diff", help="Compare deux instances qBittorrent et affiche les torrents manquants de chaque côté.")
    qdiff.add_argument("--src", required=True, help="Alias d'instance qBittorrent source.")
    qdiff.add_argument("--dst", required=True, help="Alias d'instance qBittorrent destination.")
    qdiff.add_argument(
        "--category",
        default="",
        help="Filtre une catégorie exacte côté source et destination (optionnel).",
    )
    qdiff.add_argument(
        "--limit",
        type=int,
        default=50,
        metavar="N",
        help="Limite le nombre de lignes affichées par sens (défaut: 50, 0 = illimité).",
    )
    qmirror = qsub.add_parser("mirror", help="Synchronise deux qBittorrent en copiant les torrents manquants dans la destination.")
    qmirror.add_argument("--src", required=True, help="Alias d'instance qBittorrent source.")
    qmirror.add_argument(
        "--dst",
        action="append",
        required=True,
        metavar="DST",
        help="Alias d'instance qBittorrent destination (répétable).",
    )
    qmirror.add_argument(
        "--category",
        default="",
        help="Catégorie à utiliser à l'ajout dans les destinations (défaut: catégorie `mirror_category` de chaque instance destination, sinon `calewood-mirror`).",
    )
    qmirror.add_argument(
        "--start",
        action="store_true",
        help="Démarre les torrents ajoutés dans la destination (défaut: paused).",
    )
    qmirror.add_argument(
        "--skip-checking",
        action="store_true",
        default=True,
        help="Conserve le comportement sans vérification des données (défaut: activé).",
    )
    qmirror.add_argument(
        "--force-check",
        dest="skip_checking",
        action="store_false",
        help="Force la vérification des données à l'ajout.",
    )
    qmirror.add_argument(
        "--only-category",
        default="",
        help="Filtre la source sur une catégorie exacte avant comparaison.",
    )
    qmirror.add_argument(
        "--limit",
        type=int,
        default=10,
        metavar="N",
        help="Limite le nombre de torrents copiés (défaut: 10, 0 = illimité).",
    )
    qmirror.add_argument(
        "--batch-size",
        type=int,
        default=1,
        metavar="N",
        help="Nombre maximal de torrents ajoutés par lot (défaut: 1).",
    )
    qmirror.add_argument(
        "--batch-sleep-seconds",
        type=int,
        default=5,
        metavar="S",
        help="Pause entre les lots d'ajout (défaut: 5).",
    )

    # torrents
    torrents = sub.add_parser("torrents", help="Recherche torrents (api/torrent).")
    tsub2 = torrents.add_subparsers(dest="t_cmd", required=True)
    tq = tsub2.add_parser("q", help="Recherche via `GET /api/torrent/list?q=...`.")
    tq.add_argument("q", metavar="Q", help="Recherche (nom ou sharewood_hash).")
    tq.add_argument("--limit", type=int, default=50, metavar="N", help="Nombre maximum de résultats affichés.")

    # archives
    archives = sub.add_parser("archives", help="Archivage classique (api/archive).")
    asub = archives.add_subparsers(dest="archives_cmd", required=True)
    averify = asub.add_parser("verify-my", help="Vérifie que mes archives sont présentes dans qBittorrent.")
    averify.add_argument("--qb-host", required=True, help="Alias d'instance qBittorrent (name).")
    averify.add_argument(
        "--unknown-hash",
        action="store_true",
        help="Liste les items sans lacale_hash (au lieu des absents côté qBittorrent).",
    )
    averify.add_argument(
        "--open-lacale-download",
        action="store_true",
        help="Ouvre l’URL de download La‑Cale pour chaque lacale_hash manquant (https://la-cale.space/api/torrents/download/{hash}).",
    )
    atake_budget = asub.add_parser(
        "take-budget-gib",
        help="Prend des items à archiver jusqu'à un budget (GiB), triés par taille croissante.",
    )
    atake_budget.add_argument("gib", type=int, metavar="GiB", help="Budget total en GiB (arrondi inférieur).")
    atake_budget.add_argument(
        "--status",
        default="uploaded",
        help="Filtre `status` pour `/api/archive/list` (défaut: uploaded).",
    )
    atake_budget.add_argument("--q", default="", help="Filtre `q` côté API (recherche).")
    atake_budget.add_argument("--cat", default="", help="Filtre `cat` côté API.")
    atake_budget.add_argument("--subcat", default="", help="Filtre `subcat` côté API.")
    atake_budget.add_argument(
        "--max-items",
        type=int,
        default=0,
        metavar="N",
        help="Nombre maximum d'items à prendre (0 = illimité).",
    )
    atake_budget.add_argument(
        "--complete",
        action="store_true",
        help="Enchaîne aussi `POST /api/archive/complete/{id}` (après `take`).",
    )
    atake_budget.add_argument(
        "--open-lacale-download",
        action="store_true",
        help="Après un take réussi, ouvre le lien La‑Cale de téléchargement (https://la-cale.space/api/torrents/download/{lacale_hash}).",
    )
    atake_budget.add_argument(
        "--print-lacale-download-urls",
        action="store_true",
        help="Affiche sur stdout les URLs de téléchargement La‑Cale des items sélectionnés (sans ouverture navigateur).",
    )
    atake_budget.add_argument(
        "--open-batch",
        type=int,
        default=10,
        metavar="N",
        help="Ouvre au maximum N liens à la fois (défaut: 10).",
    )
    atake_budget.add_argument(
        "--open-sleep-seconds",
        type=int,
        default=1,
        metavar="S",
        help="Pause (secondes) entre chaque batch d'ouvertures (défaut: 1).",
    )
    atake_smallest = asub.add_parser(
        "take-smallest",
        help="Prend les N plus petits items à archiver (triés par taille croissante).",
    )
    atake_smallest.add_argument("n", type=int, metavar="N", help="Nombre maximum d'items à prendre.")
    atake_smallest.add_argument(
        "--status",
        default="uploaded",
        help="Filtre `status` pour `/api/archive/list` (défaut: uploaded).",
    )
    atake_smallest.add_argument("--q", default="", help="Filtre `q` côté API (recherche).")
    atake_smallest.add_argument("--cat", default="", help="Filtre `cat` côté API.")
    atake_smallest.add_argument("--subcat", default="", help="Filtre `subcat` côté API.")
    atake_smallest.add_argument(
        "--complete",
        action="store_true",
        help="Enchaîne aussi `POST /api/archive/complete/{id}` (après `take`).",
    )
    atake_smallest.add_argument(
        "--open-lacale-download",
        action="store_true",
        help="Après un take réussi, ouvre le lien La‑Cale de téléchargement (https://la-cale.space/api/torrents/download/{lacale_hash}).",
    )
    atake_smallest.add_argument(
        "--print-lacale-download-urls",
        action="store_true",
        help="Affiche sur stdout les URLs de téléchargement La‑Cale des items sélectionnés (sans ouverture navigateur).",
    )
    atake_smallest.add_argument(
        "--open-batch",
        type=int,
        default=10,
        metavar="N",
        help="Ouvre au maximum N liens à la fois (défaut: 10).",
    )
    atake_smallest.add_argument(
        "--open-sleep-seconds",
        type=int,
        default=1,
        metavar="S",
        help="Pause (secondes) entre chaque batch d'ouvertures (défaut: 1).",
    )

    # pre-archivage
    pre = sub.add_parser("prearchivage", help="Pré-archivage (archiviste).")
    psub = pre.add_subparsers(dest="pre_cmd", required=True)
    ptake_budget = psub.add_parser(
        "take-budget-gib",
        help="Prend des items disponibles jusqu'à un budget (GiB), triés par taille croissante.",
    )
    ptake_budget.add_argument("gib", type=int, metavar="GiB", help="Budget total en GiB (arrondi inférieur).")
    ptake_budget.add_argument("--q", default="", help="Filtre `q` côté API (recherche).")
    ptake_budget.add_argument("--cat", default="", help="Filtre `cat` côté API.")
    ptake_budget.add_argument("--subcat", default="", help="Filtre `subcat` côté API.")
    ptake_budget.add_argument("--seeders", type=int, default=0, metavar="N", help="Filtre seeders>=N côté API (0 désactive).")
    ptake_budget.add_argument(
        "--max-items",
        type=int,
        default=0,
        metavar="N",
        help="Nombre maximum d'items à prendre (0 = illimité).",
    )

    # fiches (uploader)
    fiches = sub.add_parser("fiches", help="Fiches uploader (awaiting_fiche / pré-archivage upload).")
    fsub = fiches.add_subparsers(dest="f_cmd", required=True)
    ftake = fsub.add_parser("take-awaiting", help="Prend des fiches en awaiting_fiche selon filtres.")
    ftake.add_argument("category", metavar="CAT", help="Category exacte (ex: Vidéos, XXX, Audios...).")
    ftake.add_argument("--subcat", default="", metavar="SUBCAT", help='Sous-catégorie exacte (ex: "Films X").')
    ftake.add_argument("--name-regex", action="append", default=[], metavar="REGEX", help="Filtre REGEX sur le nom (répétable).")
    ftake.add_argument("--limit", type=int, default=0, metavar="N", help="Limite le nombre de prises (0 = illimité).")

    # uploads
    uploads = sub.add_parser("uploads", help="Uploads (api/upload).")
    usub = uploads.add_subparsers(dest="u_cmd", required=True)
    ucats = usub.add_parser(
        "cats-selected",
        help="Affiche les catégories disponibles pour les uploads en status=selected (avec comptage).",
    )
    ucats.add_argument(
        "--limit-pages",
        type=int,
        default=1,
        metavar="N",
        help="Nombre de pages à scanner (per_page=200). 0 = toutes les pages (plus lent).",
    )
    ucount = usub.add_parser(
        "count-done-mine",
        help="Compte mes uploads terminés, avec filtres catégorie/sous-catégorie.",
    )
    ucount.add_argument("--cat", default="", metavar="CAT", help="Category exacte à cibler (optionnel).")
    ucount.add_argument("--subcat", default="", metavar="SUBCAT", help="Sous-catégorie exacte à cibler (optionnel).")
    ucount.add_argument(
        "--status",
        default="my-uploads",
        metavar="STATUS",
        help="Valeur de `status` pour `/api/upload/list` (défaut : my-uploads).",
    )
    ucount.add_argument(
        "--no-prearchivage",
        action="store_true",
        help="N'inclut pas les fiches terminées du flux pré-archivage uploader (`/api/upload/pre-archivage/list?status=my-completed`).",
    )
    ucount.add_argument(
        "--name-regex",
        action="append",
        default=[],
        metavar="REGEX",
        help="Filtre REGEX sur le nom (répétable, insensible à la casse).",
    )
    utake = usub.add_parser("take-selected", help="Repère des uploads en status=selected, puis les prend.")
    utake.add_argument("--cat", default="", metavar="CAT", help="Category exacte à cibler (optionnel).")
    utake.add_argument("--subcat", default="", metavar="SUBCAT", help="Sous-catégorie exacte à cibler (optionnel).")
    utake.add_argument("--q", default="", metavar="Q", help="Recherche côté API (paramètre `q`, recherche par nom).")
    utake.add_argument(
        "--sort",
        default="",
        metavar="COL",
        help="Tri côté API (paramètre `sort`) : name, size_bytes, category, seeders, selected_at, uploaded_at, archived_at.",
    )
    utake.add_argument("--order", default="", metavar="asc|desc", help="Ordre côté API (paramètre `order`) : asc ou desc.")
    utake.add_argument("--name-regex", action="append", default=[], metavar="REGEX", help="Filtre REGEX sur le nom (répétable).")
    utake.add_argument(
        "--exclude-regex",
        action="append",
        default=[],
        metavar="REGEX",
        help="Exclut les uploads dont le nom matche REGEX (répétable, insensible à la casse).",
    )
    utake.add_argument("--exclude-id", action="append", default=[], metavar="ID", help="Exclut un ID d'upload (répétable).")
    utake.add_argument(
        "--exclude-ids",
        default="",
        metavar="ID1,ID2,...",
        help="Exclut une liste d'IDs (séparateurs acceptés : virgules, espaces, tabulations, retours ligne).",
    )
    utake.add_argument(
        "--only-id",
        action="append",
        default=[],
        metavar="ID",
        help="Ne garde que cet ID d'upload (répétable). Si présent, tous les autres IDs sont ignorés.",
    )
    utake.add_argument(
        "--only-ids",
        default="",
        metavar="ID1,ID2,...",
        help="Ne garde que cette liste d'IDs (séparateurs acceptés : virgules, espaces, tabulations, retours ligne).",
    )
    utake.add_argument("--limit", type=int, default=0, metavar="N", help="Limite le nombre de prises (0 = illimité).")

    ns = parser.parse_args(argv)

    if ns.cmd == "qbit" and ns.qbit_cmd == "get":
        qb = _qbit_from_instance(ns.qb_host)
        t = qb.get_torrent_by_hash(str(ns.hash))
        print(json.dumps(t, ensure_ascii=False, indent=2))
        return 0

    if ns.cmd == "qbit" and ns.qbit_cmd == "dl-queue":
        qb = _qbit_from_instance(ns.qb_host)
        torrents = qb.list_torrents(category=None)
        queued = 0
        left_bytes = 0
        for t in torrents:
            st = str(t.get("state", "") or "")
            if st in ("queuedDL", "stalledDL", "downloading", "metaDL", "allocating"):
                queued += 1
                try:
                    left_bytes += int(t.get("amount_left") or 0)
                except Exception:  # noqa: BLE001
                    pass
        left_gib = left_bytes / (1024**3)
        print(f"instance={str(ns.qb_host).lower()} queuedDL={queued} left_gib={left_gib:.2f}")
        return 0

    if ns.cmd == "qbit" and ns.qbit_cmd == "list":
        qb = _qbit_from_instance(ns.qb_host)
        category = str(ns.category or "").strip() or None
        only_state = str(ns.only_state or "").strip() or None
        limit = int(ns.limit or 0)
        torrents = qb.list_torrents(category=category)
        rows: list[tuple[str, str, str, str, str, str]] = []
        shown = 0
        for t in torrents:
            if only_state and str(t.get("state") or "").strip() != only_state:
                continue
            rows.append(
                (
                    str(t.get("hash") or "")[:12],
                    str(t.get("state") or ""),
                    str(t.get("category") or ""),
                    _fmt_gib(int(t.get("size") or 0)),
                    _fmt_gib(int(t.get("amount_left") or 0)),
                    str(t.get("name") or "")[:90],
                )
            )
            shown += 1
            if limit > 0 and shown >= limit:
                break
        _print_table(("HASH", "STATE", "CAT", "SIZE", "LEFT", "NAME"), rows)
        print(
            f"instance={str(ns.qb_host).lower()} torrents={len(torrents)} shown={shown} category={category or 'all'} only_state={only_state or 'all'}",
            file=sys.stderr,
        )
        return 0

    if ns.cmd == "qbit" and ns.qbit_cmd == "diff":
        src = _qbit_from_instance(ns.src)
        dst = _qbit_from_instance(ns.dst)
        category = str(ns.category or "").strip() or None
        limit = int(ns.limit or 50)

        src_torrents = src.list_torrents(category=category)
        dst_torrents = dst.list_torrents(category=category)
        src_hashes = {
            str(t.get("hash", "")).strip().lower(): str(t.get("name") or "") for t in src_torrents if str(t.get("hash", "")).strip()
        }
        dst_hashes = {
            str(t.get("hash", "")).strip().lower(): str(t.get("name") or "") for t in dst_torrents if str(t.get("hash", "")).strip()
        }

        src_missing = [(h, name) for h, name in src_hashes.items() if h not in dst_hashes]
        dst_missing = [(h, name) for h, name in dst_hashes.items() if h not in src_hashes]

        rows: list[tuple[str, str, str, str]] = []
        for h, name in src_missing[: limit if limit > 0 else None]:
            rows.append(("src", h[:12], "missing_dst", name[:80]))
        for h, name in dst_missing[: limit if limit > 0 else None]:
            rows.append(("dst", h[:12], "missing_src", name[:80]))

        _print_table(("SIDE", "HASH", "STATUS", "NAME"), rows)
        print(
            f"src={str(ns.src).lower()} dst={str(ns.dst).lower()} category={category or 'all'} src_torrents={len(src_torrents)} dst_torrents={len(dst_torrents)} src_missing={len(src_missing)} dst_missing={len(dst_missing)}",
            file=sys.stderr,
        )
        return 0

    if ns.cmd == "qbit" and ns.qbit_cmd == "mirror":
        src = _qbit_from_instance(ns.src)
        dst_names = [str(v).strip() for v in (ns.dst or []) if str(v).strip()]
        if not dst_names:
            raise RuntimeError("Au moins une destination `--dst` est requise.")
        dst_clients = {name: _qbit_from_instance(name) for name in dst_names}
        src_category = str(ns.only_category or "").strip() or None
        dst_category = str(ns.category or "").strip()
        start = bool(ns.start)
        skip_checking = bool(ns.skip_checking)
        limit = int(ns.limit or 0)
        batch_size = max(1, int(ns.batch_size or 1))
        batch_sleep = max(0, int(ns.batch_sleep_seconds or 5))

        src_torrents = src.list_torrents(category=src_category)
        dst_hashes_by_name = {
            name: {
                str(t.get("hash", "")).strip().lower()
                for t in client.list_torrents(category=None)
                if str(t.get("hash", "")).strip()
            }
            for name, client in dst_clients.items()
        }

        copied = 0
        scanned = 0
        missing_rows: list[tuple[str, str, str, str]] = []
        pending_batches: list[tuple[str, bytes, str, str, str]] = []
        for t in src_torrents:
            scanned += 1
            h = str(t.get("hash", "")).strip().lower()
            if not h:
                continue
            if all(h in hashes for hashes in dst_hashes_by_name.values()):
                continue
            name = str(t.get("name") or "")
            cat = str(t.get("category") or "")
            torrent_bytes = src.export_torrent_file(h)
            if not torrent_bytes:
                continue
            actions: list[str] = []
            for dst_name, dst_client in dst_clients.items():
                if h in dst_hashes_by_name[dst_name]:
                    continue
                category = dst_category or _qbit_instance_category(dst_name, "mirror_category", "calewood-mirror")
                if ns.dry_run:
                    actions.append(dst_name)
                else:
                    pending_batches.append((dst_name, torrent_bytes, category, h, name[:60]))
                    actions.append(dst_name)
            if actions:
                copied += 1
                missing_rows.append((h, cat, name[:60], ",".join(actions)))
            if limit > 0 and copied >= limit:
                break

            if not ns.dry_run and len(pending_batches) >= batch_size:
                for dst_name, torrent_bytes, category, _, _ in pending_batches:
                    dst_clients[dst_name].add_torrent_file(
                        torrent_bytes,
                        category=category,
                        start=start,
                        skip_checking=skip_checking,
                    )
                pending_batches.clear()
                if batch_sleep > 0:
                    time.sleep(batch_sleep)

        if not ns.dry_run and pending_batches:
            for dst_name, torrent_bytes, category, _, _ in pending_batches:
                dst_clients[dst_name].add_torrent_file(
                    torrent_bytes,
                    category=category,
                    start=start,
                    skip_checking=skip_checking,
                )

        _print_table(("HASH", "CAT", "NAME", "ACTION"), missing_rows)
        print(
            f"src={str(ns.src).lower()} dsts={','.join(dst_names)} scanned={scanned} copied={copied} category={dst_category or 'instance'} start={start} skip_checking={skip_checking} batch_size={batch_size} batch_sleep={batch_sleep}",
            file=sys.stderr,
        )
        return 0

    if ns.cmd == "torrents" and ns.t_cmd == "q":
        calewood = _calewood_client()
        q = str(ns.q or "").strip()
        limit = int(ns.limit or 0)
        if limit <= 0:
            limit = 50
        per_page = 200
        page = 1
        shown = 0
        rows: list[tuple[str, str, str, str, str, str]] = []
        while True:
            resp = calewood.list_torrents(q=q, p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood torrent list failed at page {page}: {resp}")
            items = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    if shown >= limit:
                        has_more = False
                        break
                    shown += 1
                    rows.append(
                        (
                            str(it.get("id") or ""),
                            str(it.get("status") or ""),
                            str(it.get("category") or ""),
                            str(it.get("subcategory") or ""),
                            str(it.get("sharewood_hash") or ""),
                            str(it.get("name") or "")[:100],
                        )
                    )
                    if ns.json:
                        if ns.jsonl:
                            print(json.dumps(it, ensure_ascii=False))
                        else:
                            print(json.dumps(it, ensure_ascii=False, indent=2))
            if not has_more:
                break
            page += 1
        if not ns.json:
            _print_table(("ID", "STATUS", "CAT", "SUBCAT", "SHAREWOOD_HASH", "NAME"), rows)
        print(f"q={q} shown={shown}", file=sys.stderr)
        return 0

    if ns.cmd == "archives" and ns.archives_cmd == "verify-my":
        calewood = _calewood_client()
        qb = _qbit_from_instance(ns.qb_host)
        qb_hashes = {str(t.get("hash", "")).lower() for t in qb.list_torrents(category=None) if str(t.get("hash", "")).strip()}

        per_page = 200
        page = 1
        missing_rows: list[tuple[str, str, str, str]] = []
        unknown_rows: list[tuple[str, str, str, str]] = []
        total = 0
        total_bytes = 0
        while True:
            resp = calewood.list_archives(status="my-archives", p=page, per_page=per_page, v1_only=0)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood archive list failed at page {page}: {resp}")
            items = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    total += 1
                    try:
                        total_bytes += int(it.get("size_bytes") or 0)
                    except Exception:  # noqa: BLE001
                        pass
                    archive_id = str(it.get("id", "") or "")
                    name = str(it.get("name", "") or "")
                    size = str(it.get("size_raw", "") or "")
                    lacale_hash = str(it.get("lacale_hash", "") or "").lower().strip()
                    if not lacale_hash:
                        unknown_rows.append((archive_id, size, "", name))
                        continue
                    if lacale_hash not in qb_hashes:
                        missing_rows.append((archive_id, size, lacale_hash, name))
                        continue
            if not has_more:
                break
            page += 1

        rows = unknown_rows if ns.unknown_hash else missing_rows
        _print_table(("ID", "SIZE", "LACALE_HASH", "NAME"), [(a, b, c, d) for (a, b, c, d) in rows])
        total_gib = total_bytes / (1024**3)
        print(
            f"my-archives total={total} missing={len(missing_rows)} unknown_hash={len(unknown_rows)} total_gib={total_gib:.2f} qb_instance={str(ns.qb_host).lower()} qb_hashes={len(qb_hashes)}",
            file=sys.stderr,
        )
        if ns.open_lacale_download:
            urls = [f"https://la-cale.space/api/torrents/download/{h}" for (_, _, h, _) in missing_rows if h]
            opened = _open_urls(urls, batch=10, sleep_seconds=1)
            print(f"opened={opened} urls={len(urls)}", file=sys.stderr)
        return 0

    if ns.cmd == "archives" and ns.archives_cmd == "take-smallest":
        calewood = _calewood_client()
        n = int(ns.n)
        if n <= 0:
            raise RuntimeError("N doit être > 0.")
        status = str(ns.status or "").strip() or "uploaded"
        q = str(ns.q or "").strip() or None
        cat = str(ns.cat or "").strip() or None
        subcat = str(ns.subcat or "").strip() or None
        do_complete = bool(ns.complete)
        open_lacale = bool(getattr(ns, "open_lacale_download", False))
        print_urls = bool(getattr(ns, "print_lacale_download_urls", False))
        open_batch = int(getattr(ns, "open_batch", 10) or 10)
        open_sleep = int(getattr(ns, "open_sleep_seconds", 1) or 1)
        items_all = _iter_archives(calewood, status=status, q=q, cat=cat, subcat=subcat, max_pages=0)
        selected = _select_smallest(items_all, n=n)

        rows: list[tuple[str, str, str, str]] = []
        took = 0
        failed = 0
        total_bytes = 0
        took_items: list[dict] = []
        for it in selected[:n]:
            aid = int(it.get("id") or 0)
            name = str(it.get("name") or "")
            sz = _size_bytes(it)
            total_bytes += max(sz, 0)
            action = "dry-run"
            if not ns.dry_run:
                try:
                    _take_archive(calewood, aid, complete=do_complete)
                    action = "took+complete" if do_complete else "took"
                    took += 1
                    took_items.append(it)
                except Exception as e:  # noqa: BLE001
                    action = f"failed: {e}"
                    failed += 1
            rows.append((str(aid), _fmt_gib(sz), name[:80], action))

        _print_table(("ID", "SIZE", "NAME", "ACTION"), rows)
        print(
            f"status={status} scanned={len(items_all)} selected={len(selected[:n])} selected_gib={(total_bytes/(1024**3)):.2f} took={took} failed={failed}",
            file=sys.stderr,
        )
        urls = _lacale_urls(took_items if not ns.dry_run else selected)
        _maybe_print_and_open_urls(
            urls,
            print_urls=print_urls,
            open_urls=open_lacale,
            batch=open_batch,
            sleep_seconds=open_sleep,
            dry_run=ns.dry_run,
        )
        return 0

    if ns.cmd == "fiches" and ns.f_cmd == "take-awaiting":
        calewood = _calewood_client()
        cat = str(ns.category or "").strip()
        subcat = str(ns.subcat or "").strip() or None
        limit = int(ns.limit or 0)
        include_res: list[re.Pattern[str]] = []
        for pat in (ns.name_regex or []):
            try:
                include_res.append(re.compile(str(pat), re.IGNORECASE))
            except re.error as e:
                raise RuntimeError(f"Regex invalide (--name-regex) : {pat!r} : {e}") from e

        def match_name(name: str) -> bool:
            if not include_res:
                return True
            return any(r.search(name or "") for r in include_res)

        per_page = 200
        page = 1
        took = 0
        rows: list[tuple[str, str, str, str, str, str]] = []
        while True:
            resp = calewood.list_upload_pre_archivage(status="", cat=cat, p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood upload/pre-archivage list failed at page {page}: {resp}")
            batch = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(batch, list):
                for it in batch:
                    if not isinstance(it, dict):
                        continue
                    name = str(it.get("name") or "")
                    if not match_name(name):
                        continue
                    if subcat and str(it.get("subcategory") or "").strip() != subcat:
                        continue
                    tid = int(it.get("id"))
                    if ns.dry_run:
                        action = "dry-run"
                    else:
                        calewood.take_upload_pre_archivage(tid)
                        action = "pris"
                        took += 1
                    rows.append(
                        (
                            str(tid),
                            str(it.get("status") or ""),
                            str(it.get("category") or ""),
                            str(it.get("subcategory") or ""),
                            str(it.get("sharewood_hash") or ""),
                            name,
                        )
                    )
                    if limit and took >= limit:
                        has_more = False
                        break
            if not has_more:
                break
            page += 1

        _print_table(("ID", "STATUS", "CAT", "SUBCAT", "HASH", "NAME"), rows)
        print(f"took={took} shown={len(rows)}", file=sys.stderr)
        return 0

    if ns.cmd == "uploads" and ns.u_cmd == "cats-selected":
        calewood = _calewood_client()
        per_page = 200
        page = 1
        max_pages = int(ns.limit_pages)
        counts: dict[str, int] = {}
        scanned = 0
        while True:
            resp = calewood.list_uploads(status="selected", p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood upload list failed at page {page}: {resp}")
            items = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    scanned += 1
                    c = str(it.get("category") or "").strip() or "(vide)"
                    counts[c] = counts.get(c, 0) + 1
            if not has_more:
                break
            page += 1
            if max_pages > 0 and page > max_pages:
                break
        rows = [(k, str(v)) for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))]
        _print_table(("CAT", "COUNT"), rows)
        print(f"scanned={scanned} cats={len(counts)} pages={page}", file=sys.stderr)
        return 0

    if ns.cmd == "uploads" and ns.u_cmd == "count-done-mine":
        calewood = _calewood_client()
        status = str(ns.status or "").strip() or "my-uploads"
        cat = str(ns.cat or "").strip() or None
        subcat = str(ns.subcat or "").strip() or None
        include_pre = not bool(ns.no_prearchivage)

        include_res: list[re.Pattern[str]] = []
        for pat in (ns.name_regex or []):
            try:
                include_res.append(re.compile(str(pat), re.IGNORECASE))
            except re.error as e:
                raise RuntimeError(f"Regex invalide (--name-regex) : {pat!r} : {e}") from e

        def match_name(name: str) -> bool:
            if not include_res:
                return True
            return any(r.search(name or "") for r in include_res)

        per_page = 200
        page = 1
        scanned = 0
        total_done = 0
        total_done_bytes = 0
        counts: dict[str, int] = {}
        scanned_pre = 0
        total_done_pre = 0
        total_done_pre_bytes = 0

        # 1) Uploads "classiques"
        while True:
            resp = calewood.list_uploads(status=status, cat=cat, subcat=subcat, p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood upload list failed at page {page}: {resp}")
            items = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    scanned += 1
                    if str(it.get("status") or "").strip().lower() != "done":
                        continue
                    name = str(it.get("name") or "")
                    if not match_name(name):
                        continue
                    total_done += 1
                    try:
                        total_done_bytes += int(it.get("size_bytes") or 0)
                    except Exception:  # noqa: BLE001
                        pass
                    c = str(it.get("category") or "").strip() or "(vide)"
                    counts[c] = counts.get(c, 0) + 1
            if not has_more:
                break
            page += 1

        # 2) Fiches terminées (pré-archivage uploader) : my-completed = post_archiving + done
        if include_pre:
            page_pre = 1
            while True:
                resp = calewood.list_upload_pre_archivage(status="my-completed", cat=cat, p=page_pre, per_page=per_page)
                if not isinstance(resp, dict) or not resp.get("success"):
                    raise RuntimeError(f"Calewood upload pre-archivage list failed at page {page_pre}: {resp}")
                items = resp.get("data")
                meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
                has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
                if isinstance(items, list):
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        scanned_pre += 1
                        # Compat: certaines réponses incluent status post_archiving/done ; on les compte comme "terminés fiche".
                        st = str(it.get("status") or "").strip().lower()
                        if st not in {"post_archiving", "done"}:
                            continue
                        if subcat:
                            if str(it.get("subcategory") or "").strip() != subcat:
                                continue
                        name = str(it.get("name") or "")
                        if not match_name(name):
                            continue
                        total_done_pre += 1
                        try:
                            total_done_pre_bytes += int(it.get("size_bytes") or 0)
                        except Exception:  # noqa: BLE001
                            pass
                        c = str(it.get("category") or "").strip() or "(vide)"
                        counts[c] = counts.get(c, 0) + 1
                if not has_more:
                    break
                page_pre += 1

        rows = [(k, str(v)) for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))]
        _print_table(("CAT", "COUNT"), rows)
        done_total = total_done + total_done_pre
        done_total_bytes = total_done_bytes + total_done_pre_bytes
        done_gib = done_total_bytes / (1024**3)
        print(
            f"status={status} scanned={scanned} done={total_done} prearchivage_scanned={scanned_pre} prearchivage_done={total_done_pre} done_total={done_total} done_gib={done_gib:.2f} cats={len(counts)} pages={page}",
            file=sys.stderr,
        )
        return 0

    if ns.cmd == "take" and ns.take_cmd == "budget-gib":
        calewood = _calewood_client()
        budget_gib = int(ns.gib)
        if budget_gib <= 0:
            raise RuntimeError("Budget GiB doit être > 0.")

        classic_status = str(ns.classic_status or "").strip()
        q = str(ns.q or "").strip() or None
        cat = str(ns.cat or "").strip() or None
        subcat = str(ns.subcat or "").strip() or None
        max_items = int(ns.max_items or 0)
        max_pages_classic = int(ns.max_pages_classic or 0)
        do_complete_classic = bool(ns.complete_classic)
        open_lacale = bool(getattr(ns, "open_lacale_download", False))
        print_urls = bool(getattr(ns, "print_lacale_download_urls", False))
        open_batch = int(getattr(ns, "open_batch", 10) or 10)
        open_sleep = int(getattr(ns, "open_sleep_seconds", 1) or 1)
        add_sw = bool(getattr(ns, "add_sharewood_to_qbit", False))
        qb_host = str(getattr(ns, "qb_host", "") or "").strip()
        qb = None
        qb_cat = "calewood-upload"
        if add_sw:
            if not qb_host:
                raise RuntimeError("--qb-host est requis avec --add-sharewood-to-qbit.")
            qb, qb_cat = _qbit_from_instance_with_upload_category(qb_host)

        items_all = _iter_archives(
            calewood,
            status=classic_status,
            q=q,
            cat=cat,
            subcat=subcat,
            max_pages=max_pages_classic,
        )
        selected, total_bytes = _select_budget(items_all, budget_gib=budget_gib, max_items=max_items)

        rows: list[tuple[str, ...]] = []
        took = 0
        failed = 0
        took_items: list[dict] = []
        for it in selected:
            tid = int(it.get("id") or 0)
            sz = _size_bytes(it)
            name = str(it.get("name") or "")
            action = "dry-run"
            if not ns.dry_run:
                try:
                    _take_archive(calewood, tid, complete=do_complete_classic)
                    action = "took+complete" if do_complete_classic else "took"
                    if add_sw:
                        torrent_bytes = calewood.download_archive_torrent_file(int(tid))
                        qb.add_torrent_file(  # type: ignore[union-attr]
                            torrent_bytes,
                            category=qb_cat,
                            start=True,
                            skip_checking=True,
                        )
                        action += "+qbit"
                    took += 1
                    took_items.append(it)
                except Exception as e:  # noqa: BLE001
                    action = f"failed: {e}"
                    failed += 1
            rows.append(("classic", str(tid), _fmt_gib(sz), name[:80], action))

        _print_table(("SRC", "ID", "SIZE", "NAME", "ACTION"), rows)
        print(
            f"scanned_classic={len(items_all)} selected={len(selected)} budget_gib={budget_gib} selected_gib={(total_bytes/(1024**3)):.2f} took={took} failed={failed}",
            file=sys.stderr,
        )
        urls = _lacale_urls(took_items if not ns.dry_run else selected)
        _maybe_print_and_open_urls(
            urls,
            print_urls=print_urls,
            open_urls=open_lacale,
            batch=open_batch,
            sleep_seconds=open_sleep,
            dry_run=ns.dry_run,
        )
        return 0

    if ns.cmd == "archives" and ns.archives_cmd == "take-budget-gib":
        calewood = _calewood_client()
        budget_gib = int(ns.gib)
        if budget_gib <= 0:
            raise RuntimeError("Budget GiB doit être > 0.")
        status = str(ns.status or "").strip()
        q = str(ns.q or "").strip() or None
        cat = str(ns.cat or "").strip() or None
        subcat = str(ns.subcat or "").strip() or None
        max_items = int(ns.max_items or 0)
        do_complete = bool(ns.complete)
        open_lacale = bool(getattr(ns, "open_lacale_download", False))
        print_urls = bool(getattr(ns, "print_lacale_download_urls", False))
        open_batch = int(getattr(ns, "open_batch", 10) or 10)
        open_sleep = int(getattr(ns, "open_sleep_seconds", 1) or 1)

        items_all = _iter_archives(calewood, status=status, q=q, cat=cat, subcat=subcat, max_pages=0)
        selected, total_bytes = _select_budget(items_all, budget_gib=budget_gib, max_items=max_items)

        rows: list[tuple[str, ...]] = []
        took = 0
        failed = 0
        took_items: list[dict] = []
        for it in selected:
            aid = int(it.get("id") or 0)
            name = str(it.get("name") or "")
            sz = _size_bytes(it)
            action = "dry-run"
            if not ns.dry_run:
                try:
                    _take_archive(calewood, aid, complete=do_complete)
                    action = "took" if not do_complete else "took+complete"
                    took += 1
                    took_items.append(it)
                except Exception as e:  # noqa: BLE001
                    action = f"failed: {e}"
                    failed += 1
            rows.append((str(aid), _fmt_gib(sz), name[:80], action))
            if ns.verbose:
                print(f"id={aid} size={sz} name={name}", file=sys.stderr)

        _print_table(("ID", "SIZE", "NAME", "ACTION"), rows)
        print(
            f"status={status} scanned={len(items_all)} selected={len(selected)} budget_gib={budget_gib} selected_gib={(total_bytes/(1024**3)):.2f} took={took} failed={failed}",
            file=sys.stderr,
        )
        urls = _lacale_urls(took_items if not ns.dry_run else selected)
        _maybe_print_and_open_urls(
            urls,
            print_urls=print_urls,
            open_urls=open_lacale,
            batch=open_batch,
            sleep_seconds=open_sleep,
            dry_run=ns.dry_run,
        )
        return 0

    if ns.cmd == "prearchivage" and ns.pre_cmd == "take-budget-gib":
        calewood = _calewood_client()
        budget_gib = int(ns.gib)
        if budget_gib <= 0:
            raise RuntimeError("Budget GiB doit être > 0.")
        budget_bytes = budget_gib * (1024**3)
        q = str(ns.q or "").strip() or None
        cat = str(ns.cat or "").strip() or None
        subcat = str(ns.subcat or "").strip() or None
        seeders = int(ns.seeders or 0)
        max_items = int(ns.max_items or 0)

        per_page = 200
        page = 1
        candidates: list[dict] = []
        scanned = 0
        while True:
            resp = calewood.list_pre_archivage(
                status=None,  # sans filtre => selected disponibles à prendre
                q=q,
                cat=cat,
                subcat=subcat,
                seeders=seeders if seeders > 0 else None,
                p=page,
                per_page=per_page,
            )
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood pre-archivage list failed at page {page}: {resp}")
            items = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    scanned += 1
                    candidates.append(it)
            if not has_more:
                break
            page += 1

        # Tri local par taille croissante
        def _sz(it: dict) -> int:
            try:
                return int(it.get("size_bytes") or 0)
            except Exception:  # noqa: BLE001
                return 0

        candidates.sort(key=_sz)

        selected: list[dict] = []
        total_bytes = 0
        for it in candidates:
            sz = _sz(it)
            if sz <= 0:
                continue
            if total_bytes + sz > budget_bytes:
                continue
            selected.append(it)
            total_bytes += sz
            if max_items > 0 and len(selected) >= max_items:
                break

        rows: list[tuple[str, ...]] = []
        took = 0
        failed = 0
        for it in selected:
            aid = int(it.get("id") or 0)
            name = str(it.get("name") or "")
            sz = _sz(it)
            action = "dry-run"
            if not ns.dry_run:
                try:
                    calewood.take_pre_archivage(aid)
                    action = "took"
                    took += 1
                except Exception as e:  # noqa: BLE001
                    action = f"failed: {e}"
                    failed += 1
            rows.append((str(aid), _fmt_gib(sz), name[:80], action))
            if ns.verbose:
                print(f"id={aid} size={sz} name={name}", file=sys.stderr)

        _print_table(("ID", "SIZE", "NAME", "ACTION"), rows)
        print(
            f"scanned={scanned} candidates={len(candidates)} selected={len(selected)} budget_gib={budget_gib} selected_gib={(total_bytes/(1024**3)):.2f} took={took} failed={failed}",
            file=sys.stderr,
        )
        return 0

    if ns.cmd == "uploads" and ns.u_cmd == "take-selected":
        calewood = _calewood_client()

        include_res: list[re.Pattern[str]] = []
        for pat in (ns.name_regex or []):
            try:
                include_res.append(re.compile(str(pat), re.IGNORECASE))
            except re.error as e:
                raise RuntimeError(f"Regex invalide (--name-regex) : {pat!r} : {e}") from e

        exclude_res: list[re.Pattern[str]] = []
        for pat in (ns.exclude_regex or []):
            try:
                exclude_res.append(re.compile(str(pat), re.IGNORECASE))
            except re.error as e:
                raise RuntimeError(f"Regex invalide (--exclude-regex) : {pat!r} : {e}") from e

        def match_name(name: str) -> bool:
            if include_res and not any(r.search(name or "") for r in include_res):
                return False
            if exclude_res and any(r.search(name or "") for r in exclude_res):
                return False
            return True

        excluded_ids: set[int] = set()
        for raw in (ns.exclude_id or []):
            s = str(raw or "").strip()
            if not s:
                continue
            excluded_ids.add(int(s))
        if str(ns.exclude_ids or "").strip():
            for part in re.split(r"[^0-9]+", str(ns.exclude_ids)):
                if part:
                    excluded_ids.add(int(part))

        only_ids: set[int] = set()
        for raw in (ns.only_id or []):
            s = str(raw or "").strip()
            if not s:
                continue
            only_ids.add(int(s))
        if str(ns.only_ids or "").strip():
            for part in re.split(r"[^0-9]+", str(ns.only_ids)):
                if part:
                    only_ids.add(int(part))

        api_status = "selected"
        api_cat = str(ns.cat or "").strip() or None
        api_subcat = str(ns.subcat or "").strip() or None
        api_q = str(ns.q or "").strip() or None
        api_sort = str(ns.sort or "").strip() or None
        api_order = str(ns.order or "").strip() or None
        limit = int(ns.limit or 0)

        per_page = 200
        page = 1
        scanned = 0
        excluded = 0
        attempted = 0
        took = 0
        failed = 0
        out: list[dict] = []

        while True:
            resp = calewood.list_uploads(
                status=api_status,
                cat=api_cat,
                subcat=api_subcat,
                q=api_q,
                sort=api_sort,
                order=api_order,
                p=page,
                per_page=per_page,
            )
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood upload list failed at page {page}: {resp}")
            items = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False

            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    scanned += 1
                    try:
                        tid = int(it.get("id"))
                    except Exception:  # noqa: BLE001
                        continue
                    if only_ids and tid not in only_ids:
                        continue
                    if tid in excluded_ids:
                        excluded += 1
                        continue
                    name = str(it.get("name") or "")
                    if not match_name(name):
                        continue

                    attempted += 1
                    if ns.dry_run:
                        if ns.verbose:
                            print(f"Dry-run: would POST /api/upload/take/{tid} ({name})", file=sys.stderr)
                    else:
                        try:
                            calewood.take_upload(tid)
                            took += 1
                            if ns.verbose:
                                print(f"Pris: {tid} {name}", file=sys.stderr)
                        except Exception as e:  # noqa: BLE001
                            failed += 1
                            if ns.verbose:
                                print(f"Échec take {tid}: {e}", file=sys.stderr)

                    if not limit or len(out) < limit:
                        out.append(it)

                    if limit:
                        if ns.dry_run:
                            if attempted >= limit:
                                has_more = False
                                break
                        else:
                            if took >= limit:
                                has_more = False
                                break

            if not has_more:
                break
            page += 1

        if ns.json:
            for it in out:
                print(json.dumps(it, ensure_ascii=False))
        else:
            headers = ("ID", "CAT", "SUBCAT", "SIZE", "SEED", "NAME", "ACTION")
            rows: list[tuple[str, str, str, str, str, str, str]] = []
            for it in out:
                tid = str(it.get("id", "") or "")
                action = "dry-run" if ns.dry_run else "pris"
                rows.append(
                    (
                        tid,
                        str(it.get("category") or ""),
                        str(it.get("subcategory") or ""),
                        str(it.get("size_raw") or ""),
                        str(it.get("seeders") or ""),
                        str(it.get("name") or ""),
                        action,
                    )
                )
            _print_table(headers, rows)

        print(
            f"scanned={scanned} excluded={excluded} matched_out={len(out)} attempted={attempted} took={took} failed={failed}",
            file=sys.stderr,
        )
        return 0 if failed == 0 else 1

    parser.print_help(sys.stderr)
    return 2
