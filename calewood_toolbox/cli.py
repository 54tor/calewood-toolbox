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
        help="Quand applicable, affiche en JSONL (1 objet JSON par ligne) au lieu d'un tableau lisible.",
    )
    parser.add_argument(
        "--seedbox-passphrase",
        type=str,
        default="",
        metavar="TEXT",
        help="Passphrase pour les endpoints Calewood `seedbox-check` (peut aussi être définie via `CALEWOOD_SEEDBOX_PASSPHRASE`).",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    # qbit
    qbit = sub.add_parser("qbit", help="Commandes qBittorrent.")
    qsub = qbit.add_subparsers(dest="qbit_cmd", required=True)
    qget = qsub.add_parser("get", help="Récupère un torrent par hash.")
    qget.add_argument("--qb-host", required=True, help="Alias d'instance qBittorrent (name).")
    qget.add_argument("hash", metavar="HASH", help="Hash qBittorrent (infohash).")

    qqueue = qsub.add_parser("dl-queue", help="Statistiques de file de téléchargement.")
    qqueue.add_argument("--qb-host", required=True, help="Alias d'instance qBittorrent (name).")

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

    # pre-archivage
    pre = sub.add_parser("prearchivage", help="Pré-archivage (archiviste).")
    psub = pre.add_subparsers(dest="pre_cmd", required=True)
    ptake = psub.add_parser("take-smallest", help="Prend les N plus petits items disponibles, puis télécharge les .torrent.")
    ptake.add_argument("n", type=int, metavar="N", help="Nombre maximum d'items à prendre.")
    ptake.add_argument("--torrent-dir", type=str, default="./downloads", metavar="DIR", help="Dossier de destination des .torrent.")
    ptake.add_argument("--q", default="", help="Filtre q=... côté API.")
    ptake.add_argument("--cat", default="", help="Filtre cat=... côté API.")
    ptake.add_argument("--subcat", default="", help="Filtre subcat=... côté API.")
    ptake.add_argument("--seeders", type=int, default=0, metavar="N", help="Filtre seeders>=N côté API (0 désactive).")

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
        help="Compte mes uploads terminés (status=my-uploads, items status==done), avec filtres catégorie/sous-catégorie.",
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
            for i, url in enumerate(urls, start=1):
                try:
                    subprocess.Popen(["xdg-open", url])  # noqa: S603,S607
                except Exception:
                    print(url)
                if i % 10 == 0:
                    time.sleep(1)
        return 0

    if ns.cmd == "prearchivage" and ns.pre_cmd == "take-smallest":
        calewood = _calewood_client()
        n = int(ns.n)
        q = str(ns.q or "").strip() or None
        cat = str(ns.cat or "").strip() or None
        subcat = str(ns.subcat or "").strip() or None
        seeders = int(ns.seeders) if int(ns.seeders) != 0 else None

        per_page = 200
        page = 1
        items_all: list[dict] = []
        while True:
            resp = calewood.list_pre_archivage(q=q, cat=cat, subcat=subcat, seeders=seeders, p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood pre-archivage list failed at page {page}: {resp}")
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
            if page > 20:
                break

        def size_bytes(it: dict) -> int:
            try:
                return int(it.get("size_bytes") or 0)
            except Exception:  # noqa: BLE001
                return 0

        chosen = sorted(items_all, key=size_bytes)[: max(0, n)]
        out_dir = Path(str(ns.torrent_dir))
        out_dir.mkdir(parents=True, exist_ok=True)
        rows: list[tuple[str, str, str, str]] = []
        for it in chosen:
            tid = int(it.get("id"))
            name = str(it.get("name") or "")
            size = str(it.get("size_raw") or "")
            if ns.dry_run:
                if ns.verbose:
                    print(f"Dry-run: would POST /api/archive/pre-archivage/take/{tid}", file=sys.stderr)
                    print(f"Dry-run: would GET /api/archive/pre-archivage/torrent-file/{tid} -> {out_dir}/{tid}.torrent", file=sys.stderr)
            else:
                calewood.take_pre_archivage(tid)
                data = calewood.download_pre_archivage_torrent_file(tid)
                (out_dir / f"{tid}.torrent").write_bytes(data)
            rows.append((str(tid), size, str(it.get("category") or ""), name))
        _print_table(("ID", "SIZE", "CAT", "NAME"), rows)
        print(f"items={len(items_all)} chosen={len(chosen)} out_dir={out_dir}", file=sys.stderr)
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

        rows = [(k, str(v)) for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))]
        _print_table(("CAT", "COUNT"), rows)
        done_gib = total_done_bytes / (1024**3)
        print(
            f"status={status} scanned={scanned} done={total_done} done_gib={done_gib:.2f} cats={len(counts)} pages={page}",
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
