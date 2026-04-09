import os
import sys
import argparse
import json
import time
from datetime import datetime
import re
from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore

    # Auto-load environment variables from a local .env file when present.
    # This must run before importing config, since config reads env at import-time.
    load_dotenv(override=False)
except Exception:
    # Keep the CLI usable even if python-dotenv isn't available for some reason.
    pass

from . import config
from .calewood import CalewoodClient


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, default)
    return value if value != "" else default


def _clip(s: object, n: int) -> str:
    """Coupe une chaîne à `n` caractères en ajoutant une ellipse si nécessaire."""
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _print_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
    """Affiche un tableau aligné (sortie humaine) à partir de `headers` + `rows`."""
    widths = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(c))
    print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    print("  ".join(("-" * widths[i]) for i in range(len(headers))))
    for r in rows:
        print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))))


def main(argv: list[str] | None = None) -> int:
    """
    CLI v2 : sous-commandes pour une aide "en étages".

    Compat : si la commande commence par un flag (ex: `--verify-my-archives-in-qbit`),
    on bascule en mode legacy (toutes les anciennes options).
    """
    argv = argv if argv is not None else sys.argv[1:]

    def build_v2_parser() -> argparse.ArgumentParser:
        v2 = argparse.ArgumentParser(prog="calewood-toolbox")
        v2.set_defaults(dry_run=True)
        dry_group = v2.add_mutually_exclusive_group(required=False)
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
        v2.add_argument(
            "--verbose",
            action="store_true",
            help="Sortie verbeuse (diagnostics).",
        )
        v2.add_argument(
            "--json",
            action="store_true",
            help="Quand applicable, affiche en JSONL (1 objet JSON par ligne) au lieu d'un tableau lisible.",
        )
        v2.add_argument(
            "--seedbox-passphrase",
            type=str,
            default="",
            metavar="TEXT",
            help="Passphrase pour les endpoints Calewood `seedbox-check` (peut aussi être définie via `CALEWOOD_SEEDBOX_PASSPHRASE`).",
        )

        sub = v2.add_subparsers(dest="cmd", required=True)

        # qbit
        qbit = sub.add_parser("qbit", help="Commandes qBittorrent.")
        qsub = qbit.add_subparsers(dest="qbit_cmd", required=True)
        qget = qsub.add_parser("get", help="Récupère un torrent par hash.")
        qget.add_argument("--qb-host", required=True, help="Alias d'instance qBittorrent (name).")
        qget.add_argument("hash", metavar="HASH", help="Hash qBittorrent (infohash).")

        qqueue = qsub.add_parser("dl-queue", help="Statistiques de file de téléchargement.")
        qqueue.add_argument("--qb-host", required=True, help="Alias d'instance qBittorrent (name).")

        # archives
        archives = sub.add_parser("archives", help="Archivage legacy (api/archive).")
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
        averify.add_argument(
            "--download-sharewood-torrent-dir",
            type=str,
            metavar="DIR",
            default="",
            help="Télécharge le .torrent Sharewood via `GET /api/upload/torrent-file/{id}` dans DIR sous la forme `{id}.torrent` (quand applicable).",
        )

        # pre-archivage
        pre = sub.add_parser("prearchivage", help="Pré-archivage (archiviste).")
        psub = pre.add_subparsers(dest="pre_cmd", required=True)
        ptake = psub.add_parser("take-smallest", help="Prend les N plus petits items disponibles, puis télécharge les .torrent.")
        ptake.add_argument("n", type=int, metavar="N", help="Nombre maximum d'items à prendre.")
        ptake.add_argument("--prearchivage-torrent-dir", type=str, default="./downloads", metavar="DIR", help="Dossier de destination des .torrent.")
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
        utake = usub.add_parser("take-selected", help="Repère des uploads en status=selected, puis les prend.")
        utake.add_argument("--cat", required=True, metavar="CAT", help="Category exacte à cibler (ex: Vidéos, XXX, Audios...).")
        utake.add_argument("--subcat", default="", metavar="SUBCAT", help="Sous-catégorie exacte à cibler (paramètre API `subcat`).")
        utake.add_argument("--q", default="", metavar="Q", help="Recherche côté API (paramètre `q`, recherche par nom).")
        utake.add_argument(
            "--sort",
            default="",
            metavar="COL",
            help="Tri côté API (paramètre `sort`) : name, size_bytes, category, seeders, selected_at, uploaded_at, archived_at.",
        )
        utake.add_argument(
            "--order",
            default="",
            metavar="asc|desc",
            help="Ordre côté API (paramètre `order`) : asc ou desc.",
        )
        utake.add_argument("--name-regex", action="append", default=[], metavar="REGEX", help="Filtre REGEX sur le nom (répétable).")
        utake.add_argument(
            "--exclude-regex",
            action="append",
            default=[],
            metavar="REGEX",
            help="Exclut les uploads dont le nom matche REGEX (répétable, insensible à la casse).",
        )
        utake.add_argument(
            "--exclude-id",
            action="append",
            default=[],
            metavar="ID",
            help="Exclut un ID d'upload (répétable).",
        )
        utake.add_argument(
            "--exclude-ids",
            default="",
            metavar="ID1,ID2,...",
            help="Exclut une liste d'IDs (séparateurs acceptés : virgules, espaces, tabulations, retours ligne).",
        )
        utake.add_argument("--limit", type=int, default=0, metavar="N", help="Limite le nombre de prises (0 = illimité).")

        return v2

    if not argv or argv[0] in ("-h", "--help"):
        build_v2_parser().print_help(sys.stderr)
        return 2
    if argv[0].startswith("--"):
        return _legacy_entry(argv)

    v2 = build_v2_parser()
    v2.set_defaults(dry_run=True)
    ns = v2.parse_args(argv)

    if ns.cmd == "uploads" and ns.u_cmd == "take-selected":
        # No legacy equivalent: implement directly in v2.
        from .calewood import CalewoodClient  # lazy import

        calewood = CalewoodClient(
            base_url=_env("CALEWOOD_BASE_URL", config.CALEWOOD_BASE_URL),
            token=_env("CALEWOOD_TOKEN", config.CALEWOOD_TOKEN),
        )

        cat = str(ns.cat or "").strip()
        if not cat:
            raise RuntimeError("--cat est obligatoire.")

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

        excluded_ids: set[int] = set()
        for raw in (ns.exclude_id or []):
            if raw is None:
                continue
            s = str(raw).strip()
            if not s:
                continue
            try:
                excluded_ids.add(int(s))
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"ID invalide (--exclude-id) : {s!r} : {e}") from e
        if str(ns.exclude_ids or "").strip():
            for part in re.split(r"[^0-9]+", str(ns.exclude_ids)):
                if not part:
                    continue
                try:
                    excluded_ids.add(int(part))
                except Exception as e:  # noqa: BLE001
                    raise RuntimeError(f"ID invalide (--exclude-ids) : {part!r} : {e}") from e

        def match_name(name: str) -> bool:
            if include_res and not any(r.search(name or "") for r in include_res):
                return False
            if exclude_res and any(r.search(name or "") for r in exclude_res):
                return False
            return True

        per_page = 200
        page = 1
        matched: list[dict] = []
        took = 0
        failed = 0
        attempted = 0
        scanned = 0
        excluded = 0
        api_q = str(ns.q or "").strip() or None
        api_subcat = str(ns.subcat or "").strip() or None
        api_sort = str(ns.sort or "").strip() or None
        api_order = str(ns.order or "").strip() or None
        while True:
            resp = calewood.list_uploads(
                status="selected",
                cat=cat,
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
                        tid_i = int(it.get("id"))
                    except Exception:  # noqa: BLE001
                        tid_i = -1
                    if tid_i > 0 and tid_i in excluded_ids:
                        excluded += 1
                        continue
                    name = str(it.get("name") or "")
                    if not match_name(name):
                        continue
                    # Take immédiatement. On n'affiche au maximum que N lignes, mais on peut scanner plus
                    # pour atteindre N prises effectives (en cas d'exclusions/erreurs).
                    if tid_i > 0:
                        attempted += 1
                        try:
                            if ns.dry_run:
                                if ns.verbose:
                                    print(f"Dry-run: would POST /api/upload/take/{tid_i} ({name})", file=sys.stderr)
                            else:
                                calewood.take_upload(tid_i)
                                took += 1
                                if ns.verbose:
                                    print(f"Pris: {tid_i} {name}", file=sys.stderr)
                        except Exception as e:  # noqa: BLE001
                            failed += 1
                            if ns.verbose:
                                print(f"Échec take {tid_i}: {e}", file=sys.stderr)

                    # Keep for table/json output (max N lignes)
                    if not ns.limit or len(matched) < int(ns.limit):
                        matched.append(it)

                    if ns.limit:
                        limit_i = int(ns.limit)
                        if not ns.dry_run:
                            if took >= limit_i:
                                has_more = False
                                break
                        else:
                            if attempted >= limit_i:
                                has_more = False
                                break
            if not has_more:
                break
            page += 1
        if ns.json:
            for it in matched:
                print(json.dumps(it, ensure_ascii=False))
            print(
                f"scanned={scanned} excluded={excluded} matched_out={len(matched)} attempted={attempted} took={took} failed={failed}",
                file=sys.stderr,
            )
        else:
            headers = ("ID", "CAT", "SUBCAT", "SIZE", "SEED", "NAME", "ACTION")
            rows: list[tuple[str, str, str, str, str, str, str]] = []
            for it in matched:
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
                f"scanned={scanned} excluded={excluded} matched_out={len(matched)} attempted={attempted} took={took} failed={failed}",
                file=sys.stderr,
            )
        return 0 if failed == 0 else 1

    if ns.cmd == "uploads" and ns.u_cmd == "cats-selected":
        from .calewood import CalewoodClient  # lazy import

        calewood = CalewoodClient(
            base_url=_env("CALEWOOD_BASE_URL", config.CALEWOOD_BASE_URL),
            token=_env("CALEWOOD_TOKEN", config.CALEWOOD_TOKEN),
        )

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
                    cat = str(it.get("category") or "").strip() or "(vide)"
                    counts[cat] = counts.get(cat, 0) + 1
            if not has_more:
                break
            page += 1
            if max_pages > 0 and page > max_pages:
                break

        rows = [(k, str(v)) for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))]
        _print_table(("CAT", "COUNT"), rows)
        print(f"scanned={scanned} cats={len(counts)} pages={page}", file=sys.stderr)
        return 0

    legacy_argv: list[str] = []
    if ns.verbose:
        legacy_argv.append("--verbose")
    if ns.json:
        legacy_argv.append("--json")
    if ns.dry_run:
        legacy_argv.append("--dry-run")
    else:
        legacy_argv.append("--just-do-it")
    if getattr(ns, "seedbox_passphrase", ""):
        legacy_argv.extend(["--seedbox-passphrase", str(ns.seedbox_passphrase)])

    if ns.cmd == "qbit" and ns.qbit_cmd == "get":
        legacy_argv.extend(["--qb-host", ns.qb_host, "--qbit-get-hash", ns.hash])
        return _legacy_entry(legacy_argv)
    if ns.cmd == "qbit" and ns.qbit_cmd == "dl-queue":
        legacy_argv.extend(["--qb-host", ns.qb_host, "--qbit-dl-queue"])
        return _legacy_entry(legacy_argv)
    if ns.cmd == "archives" and ns.archives_cmd == "verify-my":
        legacy_argv.extend(["--qb-host", ns.qb_host, "--verify-my-archives-in-qbit"])
        if ns.unknown_hash:
            legacy_argv.append("--verify-my-archives-unknown-hash")
        if ns.open_lacale_download:
            legacy_argv.append("--open-lacale-download")
        if ns.download_sharewood_torrent_dir:
            legacy_argv.extend(["--download-sharewood-torrent-dir", ns.download_sharewood_torrent_dir])
        return _legacy_entry(legacy_argv)
    if ns.cmd == "prearchivage" and ns.pre_cmd == "take-smallest":
        legacy_argv.extend(["--prearchivage-take-smallest", str(ns.n)])
        legacy_argv.extend(["--prearchivage-torrent-dir", ns.prearchivage_torrent_dir])
        if ns.q:
            legacy_argv.extend(["--prearchivage-q", ns.q])
        if ns.cat:
            legacy_argv.extend(["--prearchivage-cat", ns.cat])
        if ns.subcat:
            legacy_argv.extend(["--prearchivage-subcat", ns.subcat])
        if ns.seeders:
            legacy_argv.extend(["--prearchivage-seeders", str(ns.seeders)])
        return _legacy_entry(legacy_argv)
    if ns.cmd == "fiches" and ns.f_cmd == "take-awaiting":
        legacy_argv.extend(["--fiche-take-awaiting-category", ns.category])
        for r in ns.name_regex or []:
            legacy_argv.extend(["--fiche-take-name-regex", r])
        if ns.subcat:
            legacy_argv.extend(["--fiche-take-subcat", ns.subcat])
        if ns.limit:
            legacy_argv.extend(["--limit", str(ns.limit)])
        return _legacy_entry(legacy_argv)

    # Should be unreachable because subparsers are required.
    v2.print_help(sys.stderr)
    return 2


def _legacy_entry(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(prog="calewood-toolbox")
    parser.add_argument(
        "--qb-host",
        type=str,
        default=None,
        required=False,
        help="Alias/nom d'instance qBittorrent (champ `name`) défini dans `QBIT_INSTANCES_JSON`.",
    )
    parser.add_argument(
        "--seedbox-passphrase",
        type=str,
        default="",
        metavar="TEXT",
        help="Passphrase pour les endpoints Calewood `seedbox-check` (peut aussi être définie via `CALEWOOD_SEEDBOX_PASSPHRASE`).",
    )
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
        "--calewood-list",
        type=int,
        metavar="PER_PAGE",
        help="Teste l'auth Calewood en appelant GET /api/archive/list?per_page=PER_PAGE et affiche la réponse.",
    )
    parser.add_argument(
        "--calewood-find-lacale-hash",
        type=str,
        metavar="HASH",
        help="Trouve une archive par lacale_hash exact (toutes pages) et affiche l'item en JSON.",
    )
    parser.add_argument(
        "--calewood-find-sharewood-hash",
        type=str,
        metavar="HASH",
        help="Trouve un torrent par sharewood_hash exact via GET /api/torrent/list?q=... et affiche l'item en JSON.",
    )
    parser.add_argument(
        "--calewood-torrent-q",
        type=str,
        metavar="Q",
        help="Recherche des torrents Calewood via GET /api/torrent/list?q=Q (paginé, per_page=200) et affiche en tableau (utilise --json pour JSONL, --limit pour limiter).",
    )
    parser.add_argument(
        "--calewood-check-ids",
        type=str,
        metavar="ID1,ID2,...",
        help="Récupère /api/archive/get/{id} pour chaque id, extrait lacale_hash, et vérifie présence/complétion dans qBittorrent.",
    )
    parser.add_argument(
        "--qbit-get-hash",
        type=str,
        metavar="HASH",
        help="Récupère un torrent qBittorrent par hash exact et l'affiche en JSON.",
    )
    parser.add_argument(
        "--qbit-downloading-gib",
        action="store_true",
        help="Somme le reste à télécharger (amount_left) pour les torrents sur un hôte qBittorrent. Nécessite --qb-host.",
    )
    parser.add_argument(
        "--qbit-dl-queue",
        action="store_true",
        help=(
            'Mesure la file de téléchargement qBittorrent. Par défaut, compte les téléchargements "en attente" '
            "(amount_left>0, dlspeed==0, non paused/checking/meta), et détaille aussi queuedDL/stalledDL. Nécessite --qb-host."
        ),
    )
    parser.add_argument(
        "--qbit-stalled-zero",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--qbit-stalled-zero-blast",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--qbit-stalled-zero-delete",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--qbit-stalled-0pct-6h-prearchivage-blast",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--qbit-stalled-4h-prearchivage-blast",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--qbit-remove-tracker",
        type=str,
        metavar="URL",
        help=(
            "Retire une URL de tracker de tous les torrents sur un hôte qBittorrent. "
            "Si l'URL se termine par '*', c'est un match par préfixe. Nécessite --qb-host. Supporte --dry-run et --verbose."
        ),
    )
    parser.add_argument(
        "--qbit-add-tracker",
        type=str,
        metavar="URL",
        help="Ajoute une URL de tracker à des torrents sur un hôte qBittorrent, avec filtres optionnels. Nécessite --qb-host. Supporte --dry-run et --verbose.",
    )
    parser.add_argument(
        "--qbit-filter-name-regex",
        action="append",
        default=[],
        metavar="REGEX",
        help="Avec --qbit-add-tracker : inclut seulement les torrents dont le nom matche REGEX (répétable).",
    )
    parser.add_argument(
        "--qbit-filter-category",
        type=str,
        default="",
        metavar="CAT",
        help="Avec --qbit-add-tracker : inclut seulement les torrents de cette catégorie qBittorrent.",
    )
    parser.add_argument(
        "--qbit-filter-state",
        type=str,
        default="",
        metavar="STATE",
        help="Avec --qbit-add-tracker : inclut seulement les torrents dans cet état qBittorrent (ex: downloading, stalledDL, queuedDL).",
    )
    parser.add_argument(
        "--qbit-missing-tracker-prefix",
        type=str,
        default="",
        metavar="PREFIX",
        help=(
            "Avec --qbit-add-tracker : inclut seulement les torrents qui n'ont AUCUN tracker commençant par PREFIX. "
            "Les torrents sans tracker sont inclus."
        ),
    )
    parser.add_argument(
        "--qbit-only-no-trackers",
        action="store_true",
        help="Avec --qbit-add-tracker : inclut seulement les torrents qui n'ont actuellement aucun tracker.",
    )
    parser.add_argument(
        "--qbit-orphan-non-lacale-twins",
        action="store_true",
        help=(
            "Sur un hôte qBittorrent : construit l'ensemble des noms de torrents qui ont un tracker commençant par "
            "https://tracker.la-cale.space, puis liste tous les torrents dont le tracker ne commence PAS par ce préfixe "
            "et qui n'ont pas de jumeau La‑Cale (même nom). Nécessite --qb-host."
        ),
    )
    parser.add_argument(
        "--qbit-orphan-non-lacale-twins-delete",
        action="store_true",
        help=(
            "Avec --qbit-orphan-non-lacale-twins : supprime les torrents matchés via qBittorrent, données incluses. "
            "Utilise --limit (défaut : 1 si omis). Supporte --dry-run et --verbose."
        ),
    )
    parser.add_argument(
        "--migrate-sharewood-to-calewood",
        action="store_true",
        help=(
            "Sur un hôte qBittorrent : pour chaque torrent non‑La‑Cale en catégorie 'sharewood' ayant un jumeau La‑Cale "
            "(même nom, tracker commençant par https://tracker.la-cale.space), déplace les données du torrent Sharewood "
            "vers le chemin calewood et passe sa catégorie à 'calewood', exporte les 2 fichiers .torrent, retire les 2 "
            "torrents sans toucher aux données, puis ré‑ajoute : La‑Cale en catégorie 'calewood' avec le tag 'Moved', et "
            "Sharewood en catégorie 'cross-seed' avec le tag 'cross-seed'. Tous les re‑add utilisent skip_checking=1. "
            "Nécessite --qb-host et --migrate-from-prefix/--migrate-to-prefix. Dry-run par défaut."
        ),
    )
    parser.add_argument(
        "--migrate-from-prefix",
        type=str,
        default="",
        metavar="PATH",
        help="Avec --migrate-sharewood-to-calewood : préfixe filesystem à remplacer (ex: /downloads/sharewood).",
    )
    parser.add_argument(
        "--migrate-to-prefix",
        type=str,
        default="",
        metavar="PATH",
        help="Avec --migrate-sharewood-to-calewood : préfixe filesystem de destination (ex: /downloads/calewood).",
    )
    parser.add_argument(
        "--migrate-wait-seconds",
        type=int,
        default=0,
        metavar="S",
        help="Avec --migrate-sharewood-to-calewood : secondes à attendre après le déplacement des données (défaut : 0).",
    )
    parser.add_argument(
        "--migrate-wait-move-complete",
        action="store_true",
        default=True,
        help="Avec --migrate-sharewood-to-calewood : après set_location(), interroge qBittorrent jusqu'à fin du move (défaut : activé).",
    )
    parser.add_argument(
        "--migrate-resume-lacale",
        action="store_true",
        help="Avec --migrate-sharewood-to-calewood : reprend le torrent La‑Cale après repoint (sinon reste en pause pour éviter un recheck pendant le lag stockage).",
    )
    parser.add_argument(
        "--migrate-readd-lacale-skip-check",
        action="store_true",
        default=True,
        help=(
            "Avec --migrate-sharewood-to-calewood : au lieu de set_save_path sur le torrent La‑Cale, exporte son .torrent, "
            "le supprime (sans fichiers), puis le ré‑ajoute avec save_path et skip_checking=1 pour éviter une vérification immédiate. "
            "Recommandé si le stockage a une latence élevée (rclone/S3)."
        ),
    )
    parser.add_argument(
        "--migrate-readd-sharewood-skip-check",
        action="store_true",
        default=True,
        help=(
            "Avec --migrate-sharewood-to-calewood : après le déplacement des données Sharewood, exporte son .torrent, supprime le torrent "
            "(sans toucher aux fichiers), puis le ré‑ajoute avec save_path et skip_checking=1 pour éviter une revérification qBittorrent. "
            "Le torrent Sharewood ré‑ajouté est mis en catégorie/tag cross-seed et laissé en pause."
        ),
    )
    parser.add_argument(
        "--qbit-cycle-stop-slow-downloads",
        action="store_true",
        help=(
            "Sur un hôte qBittorrent : maintient N téléchargements actifs via un round-robin strict sur les torrents en pause. "
            "Relance un torrent, le laisse tourner ~30s, puis le conserve si le débit moyen >= 1 MiB/s ; sinon le remet en pause "
            "et passe au suivant. Nécessite --qb-host. Tourne jusqu'à Ctrl-C."
        ),
    )
    parser.add_argument(
        "--qbit-cycle-min-speed-mib",
        type=float,
        default=1.0,
        metavar="MIB",
        help="Avec --qbit-cycle-stop-slow-downloads : débit minimum en MiB/s (défaut : 1.0).",
    )
    parser.add_argument(
        "--qbit-cycle-interval-seconds",
        type=int,
        default=10,
        metavar="S",
        help="Avec --qbit-cycle-stop-slow-downloads : intervalle d'échantillonnage en secondes (défaut : 10).",
    )
    parser.add_argument(
        "--qbit-cycle-slow-for-seconds",
        type=int,
        default=10,
        metavar="S",
        help="Avec --qbit-cycle-stop-slow-downloads : ne pause que si sous le seuil depuis au moins S secondes (défaut : 10).",
    )
    parser.add_argument(
        "--qbit-cycle-probe-seconds",
        type=int,
        default=30,
        metavar="S",
        help=(
            "Avec --qbit-cycle-stop-slow-downloads : après reprise/démarrage, laisse tourner S secondes, "
            "mesure le débit moyen sur la fenêtre, et remet en pause si sous le seuil (défaut : 30)."
        ),
    )
    parser.add_argument(
        "--qbit-cycle-min-active",
        type=int,
        default=8,
        metavar="N",
        help="Avec --qbit-cycle-stop-slow-downloads : nombre cible de slots de téléchargement actifs (défaut : 8).",
    )
    parser.add_argument(
        "--seedbox-upload-prearchivage-flow",
        action="store_true",
        help=(
            "Déclenche `POST /api/upload/seedbox-check`, puis pour mes `my-uploading` avec `seedbox_progress==1` : "
            "`POST /api/upload/abandon/{id}`, `POST /api/archive/pre-archivage/take/{id}`, `POST /api/archive/pre-archivage/dl-done/{id}`. "
            "Nécessite --seedbox-passphrase ou CALEWOOD_SEEDBOX_PASSPHRASE. Supporte --dry-run et --verbose."
        ),
    )
    parser.add_argument(
        "--seedbox-upload-prearchivage-limit",
        type=int,
        default=0,
        metavar="N",
        help="Avec --seedbox-upload-prearchivage-flow : limite le nombre d'items traités (0 = illimité).",
    )
    parser.add_argument(
        "--list-my-upload-prearchivage",
        action="store_true",
        help="Liste mes fiches uploader via `GET /api/upload/pre-archivage/list?status=my-fiches` (paginé, per_page=200).",
    )
    parser.add_argument(
        "--list-my-archive-prearchivage",
        action="store_true",
        help="Liste mes pré‑archivages via `GET /api/archive/pre-archivage/list?status=my-pre-archiving` (paginé, per_page=200) et déclenche `POST /api/archive/seedbox-check`.",
    )
    parser.add_argument(
        "--list-archive-prearchivage",
        action="store_true",
        help="Liste le pool pré‑archivage via `GET /api/archive/pre-archivage/list` (tous, per_page=200). Utilise --prearchivage-status pour filtrer.",
    )
    parser.add_argument(
        "--prearchivage-status",
        metavar="STATUS",
        help="Avec --list-archive-prearchivage : filtre par status (ex : pre_archiving, awaiting_fiche, post_archiving).",
    )
    parser.add_argument(
        "--prearchivage-take",
        type=int,
        metavar="ID",
        help="POST /api/archive/pre-archivage/take/{id} (selected -> pre_archiving). Supporte --dry-run.",
    )
    parser.add_argument(
        "--prearchivage-abandon",
        type=int,
        metavar="ID",
        help="POST /api/archive/pre-archivage/abandon/{id} (pre_archiving/awaiting_fiche -> selected). Supporte --dry-run.",
    )
    parser.add_argument(
        "--prearchivage-confirm",
        type=int,
        metavar="ID",
        help="Force confirm a pre-archivage by internal id: POST /api/archive/pre-archivage/confirm/{id} (post_archiving -> done). Supporte --dry-run.",
    )
    parser.add_argument(
        "--prearchivage-blast",
        type=int,
        metavar="ID",
        help="POST /api/archive/pre-archivage/blast/{id}. Supporte --dry-run.",
    )
    parser.add_argument(
        "--prearchivage-blast-comment",
        type=str,
        metavar="TEXT",
        default="",
        help="Avec --prearchivage-blast: optional comment.",
    )
    parser.add_argument(
        "--prearchivage-torrent-file",
        type=int,
        metavar="ID",
        help="Télécharge le .torrent Sharewood via `GET /api/archive/pre-archivage/torrent-file/{id}` et l'écrit vers --prearchivage-torrent-file-out.",
    )
    parser.add_argument(
        "--prearchivage-torrent-file-out",
        type=str,
        metavar="PATH",
        default="",
        help="Avec --prearchivage-torrent-file : chemin de sortie du fichier .torrent.",
    )
    parser.add_argument(
        "--prearchivage-take-smallest",
        type=int,
        metavar="N",
        help="Liste le pool pré‑archivage (tri par taille croissante), prend jusqu'à N items, puis télécharge les .torrent Sharewood vers --prearchivage-torrent-dir. Supporte --dry-run et --verbose.",
    )
    parser.add_argument(
        "--prearchivage-q",
        type=str,
        default="",
        metavar="Q",
        help="Avec --prearchivage-take-smallest : passe `q=Q` à `/api/archive/pre-archivage/list`.",
    )
    parser.add_argument(
        "--prearchivage-cat",
        type=str,
        default="",
        metavar="CAT",
        help="Avec --prearchivage-take-smallest : passe `cat=CAT` à `/api/archive/pre-archivage/list`.",
    )
    parser.add_argument(
        "--prearchivage-subcat",
        type=str,
        default="",
        metavar="SUBCAT",
        help="Avec --prearchivage-take-smallest : passe `subcat=SUBCAT` à `/api/archive/pre-archivage/list`.",
    )
    parser.add_argument(
        "--prearchivage-seeders",
        type=int,
        default=0,
        metavar="N",
        help="Avec --prearchivage-take-smallest : passe `seeders=N` (minimum) à `/api/archive/pre-archivage/list`. 0 désactive le filtre côté API.",
    )
    parser.add_argument(
        "--prearchivage-min-size",
        type=str,
        default="",
        metavar="SIZE",
        help='Avec --prearchivage-take-smallest: pass min_size=SIZE (e.g. "500MB") to /api/archive/pre-archivage/list.',
    )
    parser.add_argument(
        "--prearchivage-max-size",
        type=str,
        default="",
        metavar="SIZE",
        help='Avec --prearchivage-take-smallest : passe `max_size=SIZE` (ex: "50GB") à `/api/archive/pre-archivage/list`.',
    )
    parser.add_argument(
        "--prearchivage-download-my-torrents",
        action="store_true",
        help=(
            "Liste mes pré‑archivages via `GET /api/archive/pre-archivage/list?status=my-pre-archiving` (paginé, per_page=200), "
            "puis télécharge chaque .torrent Sharewood via `GET /api/archive/pre-archivage/torrent-file/{id}` dans --prearchivage-torrent-dir. "
            "Supporte --dry-run, --verbose, --limit. Si --prearchivage-add-to-qbit est actif, ajoute aussi chaque .torrent à qBittorrent."
        ),
    )
    parser.add_argument(
        "--prearchivage-download-only-pre-archiving",
        action="store_true",
        help='Avec --prearchivage-download-my-torrents : inclut uniquement les items avec status=="pre_archiving".',
    )
    parser.add_argument(
        "--prearchivage-download-only-awaiting-fiche",
        action="store_true",
        help='Avec --prearchivage-download-my-torrents : inclut uniquement les items avec status=="awaiting_fiche".',
    )
    parser.add_argument(
        "--prearchivage-download-my-awaiting-fiche-torrents",
        action="store_true",
        help="Raccourci : télécharge les fichiers .torrent Sharewood pour mes pré‑archivages en status=awaiting_fiche.",
    )
    parser.add_argument(
        "--prearchivage-verify-my-awaiting-fiche-100",
        action="store_true",
        help="Vérifie que mes pré‑archivages en status=awaiting_fiche sont présents dans qBittorrent (--qb-host) et complets (progress==1.0). Nécessite --qb-host.",
    )
    parser.add_argument(
        "--prearchivage-redl-my-awaiting-fiche-not-complete",
        action="store_true",
        help=(
            "Même logique que --prearchivage-verify-my-awaiting-fiche-100 : pour mes items awaiting_fiche absents ou "
            "incomplets dans qBittorrent, retélécharge le .torrent Sharewood et le (ré)ajoute à qBittorrent "
            'category="sharewood" start=1. Si le torrent existe mais est incomplet, il est d’abord supprimé (avec fichiers). '
            "Nécessite --qb-host. Supporte --dry-run, --limit, --verbose."
        ),
    )
    parser.add_argument(
        "--prearchivage-torrent-dir",
        type=str,
        metavar="DIR",
        default=os.path.join(os.getcwd(), "downloads"),
        help="Avec --prearchivage-take-smallest : dossier de destination pour les fichiers .torrent téléchargés.",
    )
    parser.add_argument(
        "--prearchivage-add-to-qbit",
        action="store_true",
        help='Avec les téléchargements pré‑archivage : après download du .torrent, l’ajoute à qBittorrent (--qb-host) en category="sharewood" et le démarre. Supporte --dry-run.',
    )

    # Pré-archivage (Uploader) / fiches
    parser.add_argument(
        "--fiche-list",
        metavar="STATUS",
        help="Liste `/api/upload/pre-archivage/list` (paginé, per_page=200). STATUS peut être vide (awaiting_fiche), `my-fiches`, `my-completed`.",
    )
    parser.add_argument(
        "--fiche-take",
        type=int,
        metavar="ID",
        help="POST /api/upload/pre-archivage/take/{id}. Supporte --dry-run.",
    )
    parser.add_argument(
        "--fiche-take-awaiting-category",
        type=str,
        metavar="CAT",
        help=(
            "Prend en masse des fiches uploader en awaiting_fiche pour une catégorie : "
            "liste `GET /api/upload/pre-archivage/list` (paginé, per_page=200), filtre `category==CAT`, puis "
            "`POST /api/upload/pre-archivage/take/{id}`. Supporte --limit, --verbose, --dry-run/--just-do-it."
        ),
    )
    parser.add_argument(
        "--fiche-take-name-regex",
        action="append",
        default=[],
        metavar="REGEX",
        help="Avec --fiche-take-awaiting-category : inclut uniquement les fiches dont le nom matche REGEX (répétable).",
    )
    parser.add_argument(
        "--fiche-take-subcat",
        type=str,
        default="",
        metavar="SUBCAT",
        help='Avec --fiche-take-awaiting-category : inclut uniquement les fiches dont subcategory == SUBCAT (ex: "Films X").',
    )
    parser.add_argument(
        "--fiche-awaiting-video-subcats",
        action="store_true",
        help="Liste les valeurs distinctes de subcategory (avec comptage) pour category=='Vidéos' parmi les fiches awaiting_fiche.",
    )
    parser.add_argument(
        "--fiche-complete",
        type=int,
        metavar="ID",
        help="POST /api/upload/pre-archivage/complete/{id} (awaiting_fiche -> post_archiving). Nécessite --fiche-url-lacale. Supporte --dry-run.",
    )
    parser.add_argument(
        "--fiche-url-lacale",
        type=str,
        metavar="URL",
        default="",
        help="Avec --fiche-complete : valeur `url_lacale` à envoyer (ex : https://la-cale.space/torrents/...).",
    )
    parser.add_argument(
        "--fiche-abandon",
        type=int,
        metavar="ID",
        help="POST /api/upload/pre-archivage/abandon/{id}. Supporte --dry-run.",
    )
    parser.add_argument(
        "--fiche-blast",
        type=int,
        metavar="ID",
        help="POST /api/upload/pre-archivage/blast/{id} (awaiting_fiche -> new). Nécessite --fiche-reason. Supporte --dry-run.",
    )
    parser.add_argument(
        "--fiche-reason",
        type=str,
        metavar="TEXT",
        default="",
        help="Avec --fiche-blast : raison obligatoire (stockée dans le commentaire et envoyée en notification).",
    )
    parser.add_argument(
        "--fiche-scrape",
        type=int,
        metavar="ID",
        help="POST /api/upload/pre-archivage/scrape/{id}. Supporte --dry-run.",
    )
    parser.add_argument(
        "--fiche-generate-prez",
        type=int,
        metavar="ID",
        help="POST /api/upload/pre-archivage/generate-prez/{id}. Supporte --dry-run.",
    )
    parser.add_argument(
        "--fiche-verify-prez",
        type=int,
        metavar="ID",
        help="POST /api/upload/pre-archivage/verify-prez/{id}. Supporte --dry-run.",
    )
    parser.add_argument(
        "--fiche-post-lacale",
        type=int,
        metavar="ID",
        help="POST /api/upload/pre-archivage/post-lacale/{id}. Nécessite --seedbox-passphrase ou CALEWOOD_SEEDBOX_PASSPHRASE. Supporte --dry-run.",
    )
    parser.add_argument(
        "--revert-my-awaiting-fiche-to-selected",
        action="store_true",
        help="Pour mes items `/api/archive/pre-archivage/list?status=my-pre-archiving` en `awaiting_fiche` : POST /api/archive/pre-archivage/abandon/{id}, puis POST /api/upload/take/{id}. Supporte --dry-run et --verbose.",
    )
    parser.add_argument(
        "--list-my-uploading-seedbox-100",
        action="store_true",
        help="Déclenche le seedbox-check Upload, puis liste `/api/upload/list?status=my-uploading` avec `seedbox_progress==1` (per_page=200). Nécessite --seedbox-passphrase ou CALEWOOD_SEEDBOX_PASSPHRASE. Supporte --verbose.",
    )
    parser.add_argument(
        "--list-my-uploading-seedbox-100-exclude",
        action="append",
        default=[],
        metavar="REGEX",
        help="Avec --list-my-uploading-seedbox-100 : exclut les items dont le nom matche REGEX (insensible à la casse). Répétable.",
    )
    parser.add_argument(
        "--list-my-archive-prearchivage-dl-done",
        action="store_true",
        help="Avec --list-my-archive-prearchivage : pour les items avec `seedbox_progress==1`, POST /api/archive/pre-archivage/dl-done/{id}. Supporte --dry-run.",
    )
    parser.add_argument(
        "--prearchivage-dl-done-100",
        action="store_true",
        help=(
            "Pour ma file de pré‑archivage (status=my-pre-archiving + status==pre_archiving) : "
            "vérifie sur qBittorrent (--qb-host) que le torrent Sharewood est présent et complet (progress==1.0), "
            "puis POST /api/archive/pre-archivage/dl-done/{id}. Supporte --dry-run et --verbose."
        ),
    )
    parser.add_argument(
        "--prearchivage-confirm-my-post-archiving-100",
        action="store_true",
        help=(
            "Déclenche POST /api/archive/seedbox-check, puis pour mes items "
            "`/api/archive/pre-archivage/list?status=my-pre-archiving` en `post_archiving` avec `seedbox_progress==1` : "
            "vérifie que `lacale_hash` existe dans qBittorrent (--qb-host). Si absent, ouvre "
            "https://la-cale.space/api/torrents/download/{hash}. Sinon POST /api/archive/pre-archivage/confirm/{id}. "
            "Nécessite --seedbox-passphrase ou CALEWOOD_SEEDBOX_PASSPHRASE. Supporte --dry-run et --verbose."
        ),
    )
    parser.add_argument(
        "--prearchivage-download-sharewood-torrent-dir",
        type=str,
        metavar="DIR",
        default="",
        help=(
            "Avec --prearchivage-confirm-my-post-archiving-100 : télécharge le .torrent Sharewood via "
            "GET /api/archive/pre-archivage/torrent-file/{id} dans DIR sous la forme {id}.torrent pour chaque cible absente de qBittorrent "
            "(et aussi pour celles dont le lacale_hash est inconnu). Supporte --dry-run et --verbose."
        ),
    )
    parser.add_argument(
        "--process-calewood-list",
        action="store_true",
        help="Traite `/api/archive/list` : pour chaque item dont `lacale_hash` est présent dans qBittorrent, exécute POST /api/archive/take/{id} puis POST /api/archive/complete/{id}.",
    )
    parser.add_argument(
        "--qbit-missing-lacale-twins",
        action="store_true",
        help="Liste les torrents qBittorrent non trackés par La‑Cale qui n'ont pas de jumeau La‑Cale (même nom).",
    )
    parser.add_argument(
        "--qbit-without-lacale-twin",
        action="store_true",
        help="Liste tous les torrents qBittorrent (hors ceux trackés par La‑Cale) dont le nom n'a aucun jumeau parmi les torrents trackés par La‑Cale.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Avec --qbit-missing-lacale-twins : supprime chaque torrent listé et ses données via qBittorrent.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limite le nombre d'items affichés/traités (0 = illimité).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Sortie verbeuse (diagnostics).",
    )
    parser.add_argument(
        "--fs-orphans",
        type=str,
        metavar="ROOT",
        help="Scanne un dossier ROOT et affiche ce qui n'est pas géré par qBittorrent (comparaison avec les chemins content/root des torrents).",
    )
    parser.add_argument(
        "--fs-ignore",
        action="append",
        default=[],
        metavar="PATH",
        help="Chemin sous ROOT à ignorer (répétable). Exemple : /volumes/mega/1080p",
    )
    parser.add_argument(
        "--path-map",
        action="append",
        default=[],
        metavar="FROM=TO",
        help="Mappe les chemins qBittorrent vers les chemins locaux avant comparaison (répétable). Exemple : /volumes/be.cloudyfocan/mega=/mnt/.../mega",
    )
    parser.add_argument(
        "--managed-ignore-prefix",
        action="append",
        default=[],
        metavar="PREFIX",
        help="Ignore les chemins gérés par qBittorrent sous ce préfixe (répétable). Exemple : /incomplete",
    )
    parser.add_argument(
        "--check-my-uploads",
        action="store_true",
        help=(
            "Vérifie `/api/upload/list?status=my-uploading` (paginé) et contrôle que `sharewood_hash` est présent "
            "sur l'instance qBittorrent ciblée et que le torrent est complet (progress==1.0)."
        ),
    )
    parser.add_argument(
        "--calewood-upload-get",
        type=int,
        metavar="ID",
        help="Appelle `GET /api/upload/get/{id}` et affiche la réponse.",
    )
    parser.add_argument(
        "--calewood-upload-abandon",
        type=int,
        metavar="ID",
        help="POST /api/upload/abandon/{id}.",
    )
    parser.add_argument(
        "--calewood-archive-status",
        type=str,
        metavar="STATUS",
        help="Liste `/api/archive/list` avec un filtre `status` (ex : my-archiving, my-archives).",
    )
    parser.add_argument(
        "--calewood-archive-uploaded",
        action="store_true",
        help="Archivage legacy : liste les items disponibles à prendre (status=uploaded, paginé, per_page=200).",
    )
    parser.add_argument(
        "--calewood-archive-take-uploaded",
        action="store_true",
        help=(
            "Archivage legacy : prend tous les items disponibles (status=uploaded) en appelant "
            "`POST /api/archive/take/{id}` pour chacun. Supporte --dry-run, --limit, --verbose."
        ),
    )
    parser.add_argument(
        "--calewood-archive-take-uploaded-to-qbit",
        action="store_true",
        help=(
            "Archivage legacy : prend tous les items disponibles (status=uploaded), puis télécharge le .torrent La‑Cale "
            "via https://la-cale.space/api/torrents/download/{lacale_hash} et l'ajoute à l'instance qBittorrent ciblée. "
            "Nécessite --qb-host. Supporte --dry-run, --limit, --verbose."
        ),
    )
    parser.add_argument(
        "--qbit-add-category",
        type=str,
        default="calewood",
        metavar="CAT",
        help='Avec --calewood-archive-take-uploaded-to-qbit : catégorie qBittorrent à appliquer lors de l’ajout (défaut : "calewood").',
    )
    parser.add_argument(
        "--verify-my-archives-in-qbit",
        action="store_true",
        help="Récupère /api/archive/list?status=my-archives (paginé) et liste ceux absents dans qBittorrent. Nécessite --qb-host.",
    )
    parser.add_argument(
        "--verify-my-archives-unknown-hash",
        action="store_true",
        help="Avec --verify-my-archives-in-qbit : liste les items sans lacale_hash (au lieu des absents côté qBittorrent).",
    )
    parser.add_argument(
        "--open-lacale-download",
        action="store_true",
        help="Avec --verify-my-archives-in-qbit : ouvre l’URL de download La‑Cale pour chaque lacale_hash manquant (https://la-cale.space/api/torrents/download/{hash}).",
    )
    parser.add_argument(
        "--download-sharewood-torrent-dir",
        type=str,
        metavar="DIR",
        default="",
        help=(
            "Avec --verify-my-archives-in-qbit : pour chaque item manquant, télécharge le .torrent Sharewood via "
            "`GET /api/upload/torrent-file/{id}` dans DIR sous la forme `{id}.torrent`. Supporte --dry-run et --verbose."
        ),
    )
    parser.add_argument(
        "--abandon-stalled-zero",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--calewood-upload-take-low-seeders",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    # No deprecated aliases: keep CLI surface stable and explicit.
    parser.add_argument(
        "--calewood-upload-take-budget-gb",
        type=int,
        metavar="GB",
        help=(
            "Depuis la liste `seeders<=1`, prend des uploads (status=selected) en triant par taille croissante "
            "jusqu'à atteindre un budget `GB` (arrondi à l'inférieur, ne dépasse jamais)."
        ),
    )
    parser.add_argument(
        "--abandon-low-seeders",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--abandon-my-uploading-non-video",
        action="store_true",
        help=(
            "Depuis `status=my-uploading` : récupère le détail de chaque upload via `GET /api/upload/get/{id}` et "
            "abandonne (`POST /api/upload/abandon/{id}`) ceux qui ne sont pas en catégorie `Vidéos` avec sous-catégorie "
            "`Films`, `Series` ou `Films Animations`."
        ),
    )
    parser.add_argument(
        "--calewood-upload-take-ready",
        type=int,
        metavar="X",
        help=(
            "Depuis `status=selected` : prend les X plus gros uploads dont `sharewood_hash` est présent dans qBittorrent "
            "et complet (progress==1.0)."
        ),
    )
    parser.add_argument(
        "--calewood-upload-take-owned-complete",
        action="store_true",
        help=(
            "Depuis `status=selected` : prend tous les uploads dont `sharewood_hash` est présent sur `--qb-host` "
            "et complet (progress==1.0). Nécessite --qb-host. Supporte --dry-run."
        ),
    )
    parser.add_argument(
        "--calewood-upload-take-zero-seeders",
        action="store_true",
        help="Depuis `status=selected` : prend tous les uploads avec `seeders==0`.",
    )
    parser.add_argument(
        "--shutup-take-my-storage",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    # Deprecated arbitre commands: keep behavior for backward-compat but hide from --help.
    _SUPPRESS = argparse.SUPPRESS
    parser.add_argument(
        "--arbitre-q",
        metavar="Q",
        help=_SUPPRESS,
    )
    parser.add_argument(
        "--arbitre-list-q",
        metavar="Q",
        help=_SUPPRESS,
    )
    parser.add_argument("--arbitre-list-status", metavar="STATUS", help=_SUPPRESS)
    parser.add_argument("--arbitre-list-seeders", type=int, metavar="N", help=_SUPPRESS)
    parser.add_argument("--arbitre-list-sort", metavar="COL", help=_SUPPRESS)
    parser.add_argument("--arbitre-list-order", metavar="asc|desc", help=_SUPPRESS)
    parser.add_argument(
        "--arbitre-list-title-regex",
        action="append",
        default=[],
        metavar="REGEX",
        help=_SUPPRESS,
    )
    parser.add_argument(
        "--arbitre-list-ignore",
        action="store_true",
        help=_SUPPRESS,
    )
    parser.add_argument(
        "--arbitre-list-ignore-comment",
        metavar="TEXT",
        default="Auto-ignore",
        help=_SUPPRESS,
    )
    parser.add_argument(
        "--arbitre-list-select",
        action="store_true",
        help=_SUPPRESS,
    )
    parser.add_argument(
        "--arbitre-list-own",
        action="store_true",
        help=_SUPPRESS,
    )
    parser.add_argument(
        "--arbitre-take",
        action="store_true",
        help=_SUPPRESS,
    )
    parser.add_argument(
        "--arbitre-own",
        action="store_true",
        help=_SUPPRESS,
    )
    parser.add_argument(
        "--arbitre-exclude",
        action="append",
        default=[],
        metavar="REGEX",
        help=_SUPPRESS,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Quand applicable, affiche en JSONL (1 objet JSON par ligne) au lieu d'un tableau lisible.",
    )
    args = parser.parse_args(argv)

    def seedbox_passphrase_required() -> str:
        pp = str(args.seedbox_passphrase or "").strip() or str(config.CALEWOOD_SEEDBOX_PASSPHRASE or "").strip()
        if not pp:
            raise RuntimeError(
                "Passphrase seedbox requise. Fournis --seedbox-passphrase ou définis CALEWOOD_SEEDBOX_PASSPHRASE."
            )
        return pp

    def append_line_once(comment: str, line: str) -> tuple[str, bool]:
        """
        Ajoute `line` sur une nouvelle ligne sauf si elle est déjà présente (match exact, insensible à la casse).
        Retourne (new_comment, changed).
        """
        existing_lines = [l.strip() for l in str(comment or "").splitlines() if l.strip()]
        target = str(line or "").strip()
        if not target:
            return str(comment or ""), False
        if any(l.lower() == target.lower() for l in existing_lines):
            # Keep original formatting but ensure trailing newline consistency
            base = str(comment or "").rstrip("\n")
            return (base + "\n") if base else "", False
        base = str(comment or "").rstrip()
        new_comment = (base + "\n" + target).strip() + "\n"
        return new_comment, True

    def append_line_once_prefix(comment: str, *, prefix: str, line: str) -> tuple[str, bool]:
        """
        Ajoute `line` sauf si une ligne existante commence déjà par `prefix` (insensible à la casse).
        Utile quand la ligne ajoutée contient une date/heure.
        Retourne (new_comment, changed).
        """
        existing_lines = [l.strip() for l in str(comment or "").splitlines() if l.strip()]
        p = str(prefix or "").strip().lower()
        if not p:
            return append_line_once(comment, line)
        if any(l.lower().startswith(p) for l in existing_lines):
            base = str(comment or "").rstrip("\n")
            return (base + "\n") if base else "", False
        base = str(comment or "").rstrip()
        target = str(line or "").strip()
        new_comment = (base + "\n" + target).strip() + "\n"
        return new_comment, True

    def qbit_from_instance(name: str) -> "QbitClient":
        from .qbit import QbitClient  # lazy import

        n = (name or "").strip().lower()
        instances = getattr(config, "QBIT_INSTANCES", [])
        base_url = None
        username = None
        password = None
        for inst in instances:
            if not isinstance(inst, dict):
                continue
            if str(inst.get("name", "")).strip().lower() == n:
                base_url = inst.get("base_url")
                username = inst.get("username")
                password = inst.get("password")
                break
        if base_url is None:
            raise RuntimeError(f"Unknown qBittorrent instance: {name}")

        # Per-instance env overrides: QBIT_<NAME>_BASE_URL / USERNAME / PASSWORD
        prefix = f"QBIT_{n.upper()}_"
        base_url = os.environ.get(prefix + "BASE_URL", str(base_url))
        username = os.environ.get(prefix + "USERNAME", str(username))
        password = os.environ.get(prefix + "PASSWORD", str(password))

        return QbitClient(base_url=str(base_url), username=str(username), password=str(password))

    def qbit_clients(selected: str | None) -> list[tuple[str, "QbitClient"]]:
        instances = getattr(config, "QBIT_INSTANCES", [])
        if selected is not None and str(selected).strip() != "":
            n = str(selected).strip().lower()
            return [(n, qbit_from_instance(n))]
        out: list[tuple[str, "QbitClient"]] = []
        for inst in instances:
            if not isinstance(inst, dict):
                continue
            name = str(inst.get("name", "")).strip()
            if not name:
                continue
            out.append((name.lower(), qbit_from_instance(name)))
        if not out:
            raise RuntimeError("No qBittorrent instances configured (QBIT_INSTANCES).")
        return out

    def require_qb_host() -> str:
        selected = args.qb_host
        if selected is None or str(selected).strip() == "":
            raise RuntimeError("--qb-host is mandatory for this command.")
        return str(selected).strip()

    def qbit_list_optional() -> list[tuple[str, "QbitClient"]]:
        # For read-only checks, allow running on all instances when --qb-host is omitted.
        return qbit_clients(args.qb_host)

    calewood = CalewoodClient(
        base_url=_env("CALEWOOD_BASE_URL", config.CALEWOOD_BASE_URL),
        token=_env("CALEWOOD_TOKEN", config.CALEWOOD_TOKEN),
    )

    if args.calewood_list is not None:
        result = calewood.list_archives(per_page=args.calewood_list)
        print(json.dumps(result, ensure_ascii=False, indent=2) if not isinstance(result, str) else result)
        return 0
    if args.calewood_upload_get is not None:
        result = calewood.get_upload(int(args.calewood_upload_get))
        print(json.dumps(result, ensure_ascii=False, indent=2) if not isinstance(result, str) else result)
        return 0
    if args.calewood_upload_abandon is not None:
        upload_id = int(args.calewood_upload_abandon)
        if args.dry_run:
            print(f"Dry-run: would POST /api/upload/abandon/{upload_id}")
        else:
            calewood.abandon_upload(upload_id)
            print(f"Abandoned upload: {upload_id}")
        return 0
    if (
        args.calewood_archive_status is not None
        or args.calewood_archive_uploaded
        or args.calewood_archive_take_uploaded
        or args.calewood_archive_take_uploaded_to_qbit
    ):
        status = (
            "uploaded"
            if (args.calewood_archive_uploaded or args.calewood_archive_take_uploaded or args.calewood_archive_take_uploaded_to_qbit)
            else str(args.calewood_archive_status).strip()
        )
        per_page = 200
        page = 1
        items_out: list[dict] = []
        while True:
            resp = calewood.list_archives(status=status, p=page, per_page=per_page, v1_only=0)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood archive list failed at page {page}: {resp}")
            items = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict):
                        items_out.append(it)
            if not has_more:
                break
            page += 1

        if args.calewood_archive_take_uploaded or args.calewood_archive_take_uploaded_to_qbit:
            if args.calewood_archive_take_uploaded_to_qbit:
                qb_name, qb = qbit_clients(require_qb_host())[0]
                qbit_category = str(args.qbit_add_category or "").strip() or None
            else:
                qb_name, qb = ("", None)
                qbit_category = None

            # Take all items in this legacy pool.
            limit = int(args.limit or 0)
            items = items_out[:limit] if limit and limit > 0 else items_out
            took = 0
            added = 0
            download_failed = 0
            skipped = 0
            failed = 0
            missing_hash = 0
            for it in items:
                try:
                    tid = int(it.get("id"))
                except Exception:  # noqa: BLE001
                    skipped += 1
                    continue
                lacale_hash = str(it.get("lacale_hash") or "").strip().lower()
                if args.verbose:
                    print(f"Take archive {tid}: {str(it.get('name') or '')}", file=sys.stderr)
                if args.dry_run:
                    if args.calewood_archive_take_uploaded_to_qbit:
                        if not lacale_hash:
                            print(f"Dry-run: would add to qBittorrent({qb_name}) but missing lacale_hash id={tid}", file=sys.stderr)
                        else:
                            print(
                                f"Dry-run: would GET https://la-cale.space/api/torrents/download/{lacale_hash} and add to qBittorrent({qb_name}) category={qbit_category or ''}",
                                file=sys.stderr,
                            )
                    continue
                try:
                    calewood.take_archive(str(tid))
                    took += 1
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    print(f"Failed take archive {tid}: {e}", file=sys.stderr)
                    continue

                if args.calewood_archive_take_uploaded_to_qbit:
                    if not lacale_hash:
                        missing_hash += 1
                        print(f"Skip add to qBittorrent({qb_name}) id={tid}: missing lacale_hash", file=sys.stderr)
                        continue
                    url = f"https://la-cale.space/api/torrents/download/{lacale_hash}"
                    try:
                        data = calewood._request_bytes_external(url)
                    except Exception as e:  # noqa: BLE001
                        download_failed += 1
                        print(f"Failed download La-Cale torrent for {tid} ({lacale_hash}): {e} -> {url}", file=sys.stderr)
                        continue
                    try:
                        assert qb is not None
                        qb.add_torrent_file(data, category=qbit_category, start=True)
                        added += 1
                    except Exception as e:  # noqa: BLE001
                        print(f"Failed add to qBittorrent({qb_name}) id={tid}: {e}", file=sys.stderr)
                        failed += 1

            if args.dry_run:
                print(f"Dry-run: would take={len(items)} status={status}")
                return 0
            if args.calewood_archive_take_uploaded_to_qbit:
                print(
                    f"Done. took={took} added_to_qbit={added} missing_hash={missing_hash} download_failed={download_failed} skipped={skipped} failed={failed} status={status}"
                )
            else:
                print(f"Done. took={took} skipped={skipped} failed={failed} status={status}")
            return 0 if failed == 0 else 1

        if args.json:
            for it in items_out:
                print(json.dumps(it, ensure_ascii=False))
            print(f"count={len(items_out)} status={status}", file=sys.stderr)
            return 0

        def clip(s: str, n: int) -> str:
            s = s or ""
            return s if len(s) <= n else s[: n - 1] + "…"

        rows = []
        for it in items_out:
            rows.append(
                (
                    str(it.get("id", "")),
                    str(it.get("status", "") or ""),
                    clip(str(it.get("size_raw", "") or ""), 12),
                    clip(str(it.get("lacale_hash", "") or ""), 40),
                    clip(str(it.get("name", "") or ""), 80),
                )
            )
        headers = ("ID", "STATUS", "SIZE", "LACALE_HASH", "NAME")
        widths = [len(h) for h in headers]
        for r in rows:
            for i, c in enumerate(r):
                widths[i] = max(widths[i], len(c))
        print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
        print("  ".join(("-" * widths[i]) for i in range(len(headers))))
        for r in rows:
            print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))))
        print(f"\ncount={len(items_out)} status={status}", file=sys.stderr)
        return 0

    if args.verify_my_archives_in_qbit:
        import shutil
        import subprocess
        import time

        qbit_list = qbit_clients(require_qb_host())
        # Only one instance when --qb-host is provided.
        qb_name, qb = qbit_list[0]
        status = "my-archives"
        per_page = 200
        page = 1
        archives: list[dict] = []
        while True:
            resp = calewood.list_archives(status=status, p=page, per_page=per_page, v1_only=0)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood archive list failed at page {page}: {resp}")
            items = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict):
                        archives.append(it)
            if not has_more:
                break
            page += 1

        # Build an offline set of qBittorrent hashes once (much faster than per-hash lookups).
        qb_hashes: set[str] = set()
        try:
            for t in qb.list_torrents(category=None):
                h = str(t.get("hash") or "").strip().lower()
                if h:
                    qb_hashes.add(h)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"Impossible de lister les torrents qBittorrent (instance={qb_name}) : {e}") from e

        missing: list[dict] = []
        unknown_hash: list[dict] = []
        present = 0
        total_bytes = 0
        present_bytes = 0
        missing_bytes = 0
        for it in archives:
            lacale_hash = str(it.get("lacale_hash", "") or "").strip().lower()
            try:
                sz = int(it.get("size_bytes") or 0)
            except Exception:  # noqa: BLE001
                sz = 0
            if sz > 0:
                total_bytes += sz
            if not lacale_hash:
                unknown_hash.append(it)
                continue
            if lacale_hash not in qb_hashes:
                missing.append(it)
                if sz > 0:
                    missing_bytes += sz
            else:
                present += 1
                if sz > 0:
                    present_bytes += sz

        unknown_mode = bool(getattr(args, "verify_my_archives_unknown_hash", False))
        out_list = unknown_hash if unknown_mode else missing
        torrent_dir = str(getattr(args, "download_sharewood_torrent_dir", "") or "").strip()
        torrent_path = Path(torrent_dir) if torrent_dir else None
        if torrent_path is not None:
            torrent_path.mkdir(parents=True, exist_ok=True)

        if args.json:
            for it in out_list:
                print(json.dumps(it, ensure_ascii=False))
            gib = lambda b: b / (1024**3)
            print(
                f"total={len(archives)} present={present} missing={len(missing)} unknown_hash={len(unknown_hash)} "
                f"total_gib={gib(total_bytes):.2f} present_gib={gib(present_bytes):.2f} missing_gib={gib(missing_bytes):.2f}",
                file=sys.stderr,
            )
            if torrent_path is not None and not unknown_mode:
                for it in out_list:
                    try:
                        tid = int(it.get("id"))
                    except Exception:  # noqa: BLE001
                        continue
                    dest = torrent_path / f"{tid}.torrent"
                    if args.verbose:
                        print(f"Download Sharewood .torrent {tid} -> {dest}", file=sys.stderr)
                    if args.dry_run:
                        print(f"Dry-run: would GET /api/upload/torrent-file/{tid} -> {dest}", file=sys.stderr)
                        continue
                    try:
                        data = calewood.download_upload_torrent_file(tid)
                        dest.write_bytes(data)
                    except Exception as e:  # noqa: BLE001
                        print(f"Failed download Sharewood .torrent for {tid}: {e}", file=sys.stderr)

            if args.open_lacale_download and not unknown_mode:
                opener = shutil.which("xdg-open") or shutil.which("open") or shutil.which("start")
                opened = 0
                for it in out_list:
                    h = str(it.get("lacale_hash", "") or "").strip().lower()
                    if not h:
                        continue
                    url = f"https://la-cale.space/api/torrents/download/{h}"
                    if args.verbose:
                        print(f"Open {url}", file=sys.stderr)
                    if opener:
                        try:
                            subprocess.Popen([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603,S607
                            opened += 1
                            if opened % 10 == 0:
                                time.sleep(1)
                        except Exception:  # noqa: BLE001
                            print(url)
                    else:
                        print(url)
            return 0

        def clip(s: str, n: int) -> str:
            s = s or ""
            return s if len(s) <= n else s[: n - 1] + "…"

        rows = []
        for it in out_list:
            rows.append(
                (
                    str(it.get("id", "")),
                    clip(str(it.get("size_raw", "") or ""), 12),
                    clip(str(it.get("lacale_hash", "") or ""), 40),
                    clip(str(it.get("name", "") or ""), 80),
                )
            )
        headers = ("ID", "SIZE", "LACALE_HASH", "NAME")
        widths = [len(h) for h in headers]
        for r in rows:
            for i, c in enumerate(r):
                widths[i] = max(widths[i], len(c))
        print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
        print("  ".join(("-" * widths[i]) for i in range(len(headers))))
        for r in rows:
            print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))))
        gib = lambda b: b / (1024**3)
        print(
            f"\nmy-archives total={len(archives)} present={present} missing={len(missing)} unknown_hash={len(unknown_hash)} "
            f"total_gib={gib(total_bytes):.2f} present_gib={gib(present_bytes):.2f} missing_gib={gib(missing_bytes):.2f} "
            f"qb_instance={qb_name} qb_hashes={len(qb_hashes)}",
            file=sys.stderr,
        )
        if torrent_path is not None and not unknown_mode:
            for it in out_list:
                try:
                    tid = int(it.get("id"))
                except Exception:  # noqa: BLE001
                    continue
                dest = torrent_path / f"{tid}.torrent"
                if args.verbose:
                    print(f"Download Sharewood .torrent {tid} -> {dest}", file=sys.stderr)
                if args.dry_run:
                    print(f"Dry-run: would GET /api/upload/torrent-file/{tid} -> {dest}", file=sys.stderr)
                    continue
                try:
                    data = calewood.download_upload_torrent_file(tid)
                    dest.write_bytes(data)
                except Exception as e:  # noqa: BLE001
                    print(f"Failed download Sharewood .torrent for {tid}: {e}", file=sys.stderr)
        if args.open_lacale_download and not unknown_mode:
            opener = shutil.which("xdg-open") or shutil.which("open") or shutil.which("start")
            opened = 0
            for it in out_list:
                h = str(it.get("lacale_hash", "") or "").strip().lower()
                if not h:
                    continue
                url = f"https://la-cale.space/api/torrents/download/{h}"
                if args.verbose:
                    print(f"Open {url}", file=sys.stderr)
                if opener:
                    try:
                        subprocess.Popen([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603,S607
                        opened += 1
                        if opened % 10 == 0:
                            time.sleep(1)
                    except Exception:  # noqa: BLE001
                        print(url)
                else:
                    print(url)
        return 0
    if args.calewood_find_lacale_hash is not None:
        wanted = str(args.calewood_find_lacale_hash).strip().lower()
        per_page = 200
        max_pages = 500
        for page in range(1, max_pages + 1):
            resp = calewood.list_archives(p=page, per_page=per_page, v1_only=0)
            if not isinstance(resp, dict) or not resp.get("success"):
                print(f"Stop at page {page}: non-success response", file=sys.stderr)
                return 1
            items = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    lacale_hash = str(item.get("lacale_hash", "")).strip().lower()
                    if lacale_hash == wanted:
                        print(json.dumps(item, ensure_ascii=False, indent=2))
                        return 0
            if not has_more:
                break
        print(f"Not found: lacale_hash={wanted}", file=sys.stderr)
        return 2
    if args.calewood_find_sharewood_hash is not None:
        wanted = str(args.calewood_find_sharewood_hash).strip().lower()
        per_page = 200
        page = 1
        while True:
            resp = calewood.list_torrents(q=wanted, p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood torrent list failed at page {page}: {resp}")
            items = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    sh = str(item.get("sharewood_hash", "")).strip().lower()
                    if sh == wanted:
                        print(json.dumps(item, ensure_ascii=False, indent=2))
                        return 0
            if not has_more:
                break
            page += 1
        print(f"Not found: sharewood_hash={wanted}", file=sys.stderr)
        return 2
    if args.calewood_torrent_q is not None:
        q = str(args.calewood_torrent_q).strip()
        per_page = 200
        page = 1
        out: list[dict] = []
        while True:
            resp = calewood.list_torrents(q=q, p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood torrent list failed at page {page}: {resp}")
            items = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict):
                        out.append(it)
                        if args.limit and len(out) >= int(args.limit):
                            has_more = False
                            break
            if not has_more:
                break
            page += 1

        if args.json:
            for it in out:
                print(json.dumps(it, ensure_ascii=False))
        else:
            headers = ("ID", "STATUS", "CAT", "SUBCAT", "SIZE", "SEED", "SW_HASH", "LACALE_HASH", "NAME")
            rows: list[tuple[str, ...]] = []
            for it in out:
                rows.append(
                    (
                        str(it.get("id", "")),
                        str(it.get("status", "") or ""),
                        _clip(str(it.get("category", "") or ""), 10),
                        _clip(str(it.get("subcategory", "") or ""), 16),
                        _clip(str(it.get("size_raw", "") or ""), 12),
                        str(it.get("seeders", "") or ""),
                        _clip(str(it.get("sharewood_hash", "") or ""), 40),
                        _clip(str(it.get("lacale_hash", "") or ""), 40),
                        _clip(str(it.get("name", "") or ""), 80),
                    )
                )
            _print_table(headers, rows)
        print(f"count={len(out)} q={q}", file=sys.stderr)
        return 0
    if args.calewood_check_ids is not None:
        raw_ids = [s.strip() for s in str(args.calewood_check_ids).split(",") if s.strip()]
        ids: list[int] = []
        for s in raw_ids:
            try:
                ids.append(int(s))
            except ValueError:
                print(f"Invalid id: {s}", file=sys.stderr)
                return 2

        # Fetch Calewood archives first (no qBittorrent dependency yet).
        rows: list[dict] = []
        hashes: list[str] = []
        for archive_id in ids:
            resp = calewood.get_archive(archive_id)
            if not isinstance(resp, dict) or not resp.get("success"):
                rows.append({"id": archive_id, "error": resp})
                continue
            data = resp.get("data")
            if not isinstance(data, dict):
                rows.append({"id": archive_id, "error": "unexpected data"})
                continue
            lacale_hash = str(data.get("lacale_hash", "")).strip().lower()
            name = str(data.get("name", "")).strip()
            hashes.append(lacale_hash)
            rows.append({"id": archive_id, "lacale_hash": lacale_hash, "name": name})

        for row in rows:
            lacale_hash = row.get("lacale_hash")
            if not isinstance(lacale_hash, str) or not lacale_hash:
                print(json.dumps(row, ensure_ascii=False))
                continue
            t = None
            for _, qb in qbit_list:
                try:
                    t = qb.get_torrent_by_hash(lacale_hash)
                    if t:
                        break
                except Exception:  # noqa: BLE001
                    continue
            if not t:
                row["qbittorrent"] = "missing"
            else:
                row["qbittorrent"] = {
                    "name": t.get("name"),
                    "progress": t.get("progress"),
                    "state": t.get("state"),
                    "tags": t.get("tags"),
                }
            print(json.dumps(row, ensure_ascii=False))
        return 0
    if args.qbit_get_hash is not None:
        wanted = str(args.qbit_get_hash).strip()
        any_found = False
        for name, qb in qbit_clients(args.qb_host):
            t = qb.get_torrent_by_hash(wanted)
            if t is not None:
                any_found = True
            print(json.dumps({"instance": name, "torrent": t}, ensure_ascii=False, indent=2))
        if not any_found:
            return 2
        return 0

    if args.qbit_downloading_gib:
        qbit_list = qbit_clients(require_qb_host())
        # Only one instance when --qb-host is provided.
        name, qb = qbit_list[0]
        torrents = qb.list_torrents(category=None)
        downloading = []
        total_left = 0
        total_speed = 0
        for t in torrents:
            try:
                left = int(t.get("amount_left") or 0)
            except Exception:  # noqa: BLE001
                left = 0
            if left <= 0:
                continue
            total_left += left
            try:
                total_speed += int(t.get("dlspeed") or 0)
            except Exception:  # noqa: BLE001
                pass
            downloading.append(t)

        gib_left = total_left / (1024**3)
        mib_s = total_speed / (1024**2)
        print(f"instance={name} downloading={len(downloading)} left_gib={gib_left:.2f} dlspeed_mib_s={mib_s:.2f}")
        if args.verbose and downloading:
            # Largest remaining first.
            downloading.sort(key=lambda t: int(t.get("amount_left") or 0), reverse=True)
            for t in downloading[:20]:
                left = int(t.get("amount_left") or 0)
                print(f"  left_gib={left / (1024**3):.2f} name={t.get('name')}", file=sys.stderr)
        return 0

    if args.qbit_dl_queue:
        qbit_list = qbit_clients(require_qb_host())
        name, qb = qbit_list[0]
        torrents = qb.list_torrents(category=None)

        waiting: list[dict] = []
        queued_dl: list[dict] = []
        stalled_dl: list[dict] = []
        active_dl: list[dict] = []
        total_left_waiting = 0
        for t in torrents:
            try:
                left = int(t.get("amount_left") or 0)
            except Exception:  # noqa: BLE001
                left = 0
            if left <= 0:
                continue
            state = str(t.get("state") or "")
            try:
                speed = int(t.get("dlspeed") or 0)
            except Exception:  # noqa: BLE001
                speed = 0

            if speed > 0:
                active_dl.append(t)
                continue

            if state in {"pausedDL", "checkingDL", "metaDL"}:
                continue

            waiting.append(t)
            total_left_waiting += left
            if state == "queuedDL":
                queued_dl.append(t)
            if state == "stalledDL":
                stalled_dl.append(t)

        waiting.sort(key=lambda t: int(t.get("amount_left") or 0), reverse=True)

        if args.json:
            print(
                json.dumps(
                    {
                        "instance": name,
                        "waiting": len(waiting),
                        "queuedDL": len(queued_dl),
                        "stalledDL": len(stalled_dl),
                        "active": len(active_dl),
                        "bytes_left_waiting": total_left_waiting,
                        "gib_left_waiting": total_left_waiting / (1024**3),
                    },
                    ensure_ascii=False,
                )
            )
            return 0

        gib_left = total_left_waiting / (1024**3)
        print(
            f"instance={name} waiting={len(waiting)} queuedDL={len(queued_dl)} stalledDL={len(stalled_dl)} active={len(active_dl)} left_gib_waiting={gib_left:.2f}"
        )
        if args.verbose and waiting:
            for t in waiting[:20]:
                left = int(t.get("amount_left") or 0)
                print(
                    f"  state={t.get('state')} left_gib={left / (1024**3):.2f} name={t.get('name')}",
                    file=sys.stderr,
                )
        return 0

    if args.qbit_stalled_zero:
        qbit_list = qbit_clients(require_qb_host())
        name, qb = qbit_list[0]
        torrents = qb.list_torrents(category=None)

        stalled: list[dict] = []
        for t in torrents:
            try:
                left = int(t.get("amount_left") or 0)
            except Exception:  # noqa: BLE001
                left = 0
            if left <= 0:
                continue
            state = str(t.get("state") or "")
            # Not "in queue" (queuedDL) and not explicitly paused.
            if state in {"queuedDL", "pausedDL", "checkingDL", "metaDL"}:
                continue
            try:
                speed = int(t.get("dlspeed") or 0)
            except Exception:  # noqa: BLE001
                speed = 0
            if speed != 0:
                continue
            stalled.append(t)

        stalled.sort(key=lambda t: int(t.get("amount_left") or 0), reverse=True)

        if args.json:
            for t in stalled:
                print(json.dumps({"instance": name, "torrent": t}, ensure_ascii=False))
            print(f"instance={name} stalled_zero={len(stalled)}", file=sys.stderr)
            return 0

        def clip(s: str, n: int) -> str:
            s = s or ""
            return s if len(s) <= n else s[: n - 1] + "…"

        headers = ("HASH", "STATE", "PROG", "LEFT_GIB", "NAME")
        rows: list[tuple[str, str, str, str, str]] = []
        for t in stalled:
            left = int(t.get("amount_left") or 0)
            prog = float(t.get("progress") or 0.0)
            rows.append(
                (
                    clip(str(t.get("hash") or ""), 40),
                    clip(str(t.get("state") or ""), 12),
                    f"{prog:.3f}",
                    f"{left / (1024**3):.2f}",
                    clip(str(t.get("name") or ""), 80),
                )
            )
        widths = [len(h) for h in headers]
        for r in rows:
            for i, c in enumerate(r):
                widths[i] = max(widths[i], len(c))
        print(f"instance={name}")
        print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
        print("  ".join(("-" * widths[i]) for i in range(len(headers))))
        for r in rows:
            print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))))
        print(f"\nstalled_zero={len(stalled)}", file=sys.stderr)
        return 0

    if args.qbit_remove_tracker is not None:
        qbit_list = qbit_clients(require_qb_host())
        name, qb = qbit_list[0]
        wanted = str(args.qbit_remove_tracker or "").strip()
        if not wanted:
            raise RuntimeError("--qbit-remove-tracker URL is required.")
        is_prefix = wanted.endswith("*")
        wanted_prefix = wanted[:-1] if is_prefix else ""
        if is_prefix and not wanted_prefix:
            raise RuntimeError("--qbit-remove-tracker prefix cannot be empty.")

        torrents = qb.list_torrents(category=None)
        if args.limit:
            torrents = torrents[: int(args.limit)]
        matched_torrents = 0
        urls_total = 0
        skipped = 0
        failed = 0

        for idx, t in enumerate(torrents, start=1):
            h = str(t.get("hash") or "").strip()
            if not h:
                skipped += 1
                continue
            if args.verbose and (idx == 1 or idx % 200 == 0):
                print(f"Scanning trackers: {idx}/{len(torrents)}", file=sys.stderr)
            try:
                trackers = qb.list_trackers(h)
            except Exception as e:  # noqa: BLE001
                failed += 1
                if args.verbose:
                    print(f"Failed list trackers {h} ({t.get('name')}): {e}", file=sys.stderr)
                continue

            urls: list[str] = []
            for tr in trackers:
                url = str(tr.get("url") or "").strip()
                if not url:
                    continue
                if is_prefix:
                    if url.startswith(wanted_prefix):
                        urls.append(url)
                else:
                    if url == wanted:
                        urls.append(url)

            if not urls:
                continue

            matched_torrents += 1
            urls_total += len(urls)
            if args.verbose:
                print(f"Match {h} name={t.get('name')} remove={len(urls)}", file=sys.stderr)
                for u in urls:
                    print(f"  {u}", file=sys.stderr)

            if args.dry_run:
                continue

            try:
                qb.remove_trackers(h, urls)
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed remove trackers {h} ({t.get('name')}): {e}", file=sys.stderr)

        if args.dry_run:
            print(f"Dry-run: instance={name} matched_torrents={matched_torrents} trackers_to_remove={urls_total} skipped={skipped} failed={failed}")
        else:
            print(f"Done. instance={name} matched_torrents={matched_torrents} removed={urls_total} skipped={skipped} failed={failed}")
        return 0 if failed == 0 else 1

    if args.qbit_add_tracker is not None:
        qbit_list = qbit_clients(require_qb_host())
        name, qb = qbit_list[0]
        tracker_url = str(args.qbit_add_tracker or "").strip()
        if not tracker_url:
            raise RuntimeError("--qbit-add-tracker URL is required.")

        category_filter = str(args.qbit_filter_category or "").strip()
        state_filter = str(args.qbit_filter_state or "").strip()
        missing_prefix = str(args.qbit_missing_tracker_prefix or "").strip()
        only_no_trackers = bool(getattr(args, "qbit_only_no_trackers", False))
        regexes_raw = [str(r) for r in (args.qbit_filter_name_regex or []) if str(r or "").strip()]
        regexes = [re.compile(r, re.IGNORECASE) for r in regexes_raw]

        torrents = qb.list_torrents(category=category_filter or None)
        if args.limit:
            torrents = torrents[: int(args.limit)]

        candidates = 0
        matched = 0
        added = 0
        skipped = 0
        failed = 0
        for idx, t in enumerate(torrents, start=1):
            h = str(t.get("hash") or "").strip()
            if not h:
                skipped += 1
                continue

            if args.verbose and (idx == 1 or idx % 200 == 0):
                print(f"Scanning torrents: {idx}/{len(torrents)}", file=sys.stderr)

            name_t = str(t.get("name") or "")
            if regexes and not any(r.search(name_t) for r in regexes):
                continue
            if state_filter:
                if str(t.get("state") or "") != state_filter:
                    continue

            candidates += 1
            try:
                trackers = qb.list_trackers(h)
            except Exception as e:  # noqa: BLE001
                failed += 1
                if args.verbose:
                    print(f"Failed list trackers {h} ({name_t}): {e}", file=sys.stderr)
                continue

            urls = [str(tr.get("url") or "").strip() for tr in trackers if str(tr.get("url") or "").strip()]
            real_urls = [u for u in urls if u.startswith("http://") or u.startswith("https://")]

            if only_no_trackers and real_urls:
                continue

            # Skip if already has tracker_url exactly.
            if tracker_url in urls:
                continue

            # If requested, only include torrents missing a whole tracker family/prefix.
            if missing_prefix:
                if any(u.startswith(missing_prefix) for u in urls):
                    continue

            matched += 1
            if args.verbose:
                print(f"Add tracker to {h} name={name_t}", file=sys.stderr)
                if not real_urls:
                    print("  (no real trackers)", file=sys.stderr)
                elif missing_prefix:
                    # Show first few existing trackers when filtering by prefix.
                    for u in urls[:5]:
                        print(f"  existing {u}", file=sys.stderr)
                print(f"  add {tracker_url}", file=sys.stderr)

            if args.dry_run:
                continue

            try:
                qb.add_trackers(h, tracker_url)
                added += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed add tracker {h} ({name_t}): {e}", file=sys.stderr)

        if args.dry_run:
            print(
                f"Dry-run: instance={name} candidates={candidates} matched={matched} would_add={matched} skipped={skipped} failed={failed}"
            )
        else:
            print(f"Done. instance={name} candidates={candidates} matched={matched} added={added} skipped={skipped} failed={failed}")
        return 0 if failed == 0 else 1

    if args.qbit_orphan_non_lacale_twins:
        qb_name, qb = qbit_clients(require_qb_host())[0]
        prefix = "https://tracker.la-cale.space"

        torrents = qb.list_torrents(category=None)
        lacale_names: set[str] = set()
        for t in torrents:
            tracker = str(t.get("tracker") or "").strip()
            if tracker.startswith(prefix):
                name_t = str(t.get("name") or "")
                if name_t:
                    lacale_names.add(name_t)

        # Ignore torrents that are currently involved in Calewood legacy archivage or pre-archivage flows,
        # so we don't accidentally delete/flag something that is in-progress.
        ignore_hashes: set[str] = set()
        ignore_names: set[str] = set()

        def _page_collect_legacy(status: str) -> None:
            per_page = 200
            p = 1
            while True:
                resp = calewood.list_archives(status=status, p=p, per_page=per_page, v1_only=0)
                if not isinstance(resp, dict) or not resp.get("success"):
                    break
                batch = resp.get("data")
                meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
                has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
                if isinstance(batch, list):
                    for it in batch:
                        if not isinstance(it, dict):
                            continue
                        nm = str(it.get("name") or "").strip()
                        if nm:
                            ignore_names.add(nm)
                        for k in ("lacale_hash", "sharewood_hash"):
                            h = str(it.get(k) or "").strip().lower()
                            if h:
                                ignore_hashes.add(h)
                if not has_more:
                    break
                p += 1

        def _page_collect_prearchivage(status: str) -> None:
            per_page = 200
            p = 1
            while True:
                resp = calewood.list_pre_archivage(status=status, p=p, per_page=per_page)
                if not isinstance(resp, dict) or not resp.get("success"):
                    break
                batch = resp.get("data")
                meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
                has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
                if isinstance(batch, list):
                    for it in batch:
                        if not isinstance(it, dict):
                            continue
                        nm = str(it.get("name") or "").strip()
                        if nm:
                            ignore_names.add(nm)
                        for k in ("lacale_hash", "sharewood_hash"):
                            h = str(it.get(k) or it.get(k.replace("_hash", "Hash")) or "").strip().lower()
                            if h:
                                ignore_hashes.add(h)
                if not has_more:
                    break
                p += 1

        # Best-effort: if Calewood is down, just proceed without those ignores.
        try:
            _page_collect_legacy("uploaded")
            _page_collect_legacy("my-archiving")
        except Exception as e:  # noqa: BLE001
            if args.verbose:
                print(f"Warning: failed to load legacy archivage ignores: {e}", file=sys.stderr)
        try:
            _page_collect_prearchivage("my-pre-archiving")
        except Exception as e:  # noqa: BLE001
            if args.verbose:
                print(f"Warning: failed to load pre-archivage ignores: {e}", file=sys.stderr)

        orphans: list[dict] = []
        for t in torrents:
            name_t = str(t.get("name") or "")
            if not name_t:
                continue
            if str(t.get("category") or "").strip().lower() == "cross-seed":
                continue
            h_t = str(t.get("hash") or "").strip().lower()
            if h_t and h_t in ignore_hashes:
                continue
            if name_t in ignore_names:
                continue
            tracker = str(t.get("tracker") or "").strip()
            if tracker.startswith(prefix):
                continue
            if name_t in lacale_names:
                continue
            orphans.append(t)

        if args.json:
            for t in orphans:
                print(json.dumps(t, ensure_ascii=False))
            print(f"count={len(orphans)} qb_instance={qb_name} lacale_names={len(lacale_names)} total={len(torrents)}", file=sys.stderr)
            return 0

        def clip(s: str, n: int) -> str:
            s = s or ""
            return s if len(s) <= n else s[: n - 1] + "…"

        rows = []
        for t in sorted(orphans, key=lambda x: str(x.get("name") or "").lower()):
            rows.append(
                (
                    clip(str(t.get("hash") or ""), 12),
                    clip(str(t.get("category") or ""), 12),
                    clip(str(t.get("size_raw") or t.get("size") or ""), 12),
                    clip(str(t.get("tracker") or ""), 40),
                    clip(str(t.get("name") or ""), 80),
                )
            )
        headers = ("HASH", "CAT", "SIZE", "TRACKER", "NAME")
        widths = [len(h) for h in headers]
        for r in rows:
            for i, c in enumerate(r):
                widths[i] = max(widths[i], len(c))
        print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
        print("  ".join(("-" * widths[i]) for i in range(len(headers))))
        for r in rows:
            print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))))
        print(f"\ncount={len(orphans)} qb_instance={qb_name} lacale_names={len(lacale_names)} total={len(torrents)}", file=sys.stderr)

        if args.qbit_orphan_non_lacale_twins_delete:
            limit = int(args.limit or 0) if args.limit is not None else 0
            if limit <= 0:
                limit = 1
            deleted = 0
            skipped = 0
            failed = 0
            for t in orphans[:limit]:
                h = str(t.get("hash") or "").strip()
                name_t = str(t.get("name") or "")
                if not h:
                    skipped += 1
                    continue
                if args.verbose:
                    print(f"Delete orphan {h}: {name_t}", file=sys.stderr)
                if args.dry_run:
                    continue
                try:
                    qb.delete_torrent(h, delete_files=True)
                    deleted += 1
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    print(f"Failed delete {h} ({name_t}): {e}", file=sys.stderr)
            if args.dry_run:
                print(f"Dry-run: would delete={min(limit, len(orphans))} qb_instance={qb_name}")
                return 0
            print(f"Done. deleted={deleted} skipped={skipped} failed={failed} qb_instance={qb_name}")
            return 0 if failed == 0 else 1

        return 0

    if args.migrate_sharewood_to_calewood:
        import time

        qb_name, qb = qbit_clients(require_qb_host())[0]
        prefix = "https://tracker.la-cale.space"
        from_prefix = str(args.migrate_from_prefix or "").rstrip("/")
        to_prefix = str(args.migrate_to_prefix or "").rstrip("/")
        wait_s = int(args.migrate_wait_seconds or 0)
        resume_lacale = bool(args.migrate_resume_lacale)
        readd_skip = bool(args.migrate_readd_lacale_skip_check)
        readd_sw = bool(args.migrate_readd_sharewood_skip_check)
        wait_move = bool(args.migrate_wait_move_complete)
        if not from_prefix or not to_prefix:
            raise RuntimeError("--migrate-from-prefix and --migrate-to-prefix are required.")
        if wait_s < 0:
            raise RuntimeError("--migrate-wait-seconds must be >= 0")

        torrents = qb.list_torrents(category=None)

        # Index La-Cale torrents by name (exact match).
        lacale_by_name: dict[str, dict] = {}
        for t in torrents:
            tracker = str(t.get("tracker") or "").strip()
            if not tracker.startswith(prefix):
                continue
            name_t = str(t.get("name") or "").strip()
            if not name_t:
                continue
            lacale_by_name[name_t] = t

        # Find Sharewood candidates by category.
        candidates: list[tuple[dict, dict]] = []
        for t in torrents:
            name_t = str(t.get("name") or "").strip()
            if not name_t or name_t not in lacale_by_name:
                continue
            if str(t.get("category") or "").strip().lower() != "sharewood":
                continue
            tracker = str(t.get("tracker") or "").strip()
            if tracker.startswith(prefix):
                continue
            if str(t.get("category") or "").strip().lower() == "cross-seed":
                continue
            candidates.append((t, lacale_by_name[name_t]))

        # Deterministic order: biggest first (move fewer big ones early might be risky; but user didn't specify).
        candidates.sort(key=lambda pair: int(pair[0].get("size") or 0), reverse=True)

        limit = int(args.limit or 0) if args.limit is not None else 0
        if limit <= 0:
            limit = 1
        chosen = candidates[: min(limit, len(candidates))]

        moved = 0
        repointed = 0
        tagged_old = 0
        skipped = 0
        failed = 0

        def _map_prefix(path: str) -> str | None:
            p = str(path or "").rstrip("/")
            if not p:
                return None
            if p == from_prefix or p.startswith(from_prefix + "/"):
                return to_prefix + p[len(from_prefix) :]
            return None

        for sw, lc in chosen:
            sw_hash = str(sw.get("hash") or "").strip()
            lc_hash = str(lc.get("hash") or "").strip()
            name_t = str(sw.get("name") or "")
            sw_save = str(sw.get("save_path") or sw.get("download_path") or "").strip()
            new_save = _map_prefix(sw_save)
            if not sw_hash or not lc_hash or not sw_save or not new_save:
                skipped += 1
                if args.verbose:
                    print(
                        f"Skip migrate (missing fields) name={name_t} sw_hash={sw_hash} lc_hash={lc_hash} save_path={sw_save!r}",
                        file=sys.stderr,
                    )
                continue

            if args.verbose:
                print(f"Migrate: {name_t}", file=sys.stderr)
                print(f"  sw  hash={sw_hash} save_path={sw_save} -> {new_save}", file=sys.stderr)
                print(f"  lc  hash={lc_hash} category={lc.get('category')} save_path={lc.get('save_path')}", file=sys.stderr)

            if args.dry_run:
                print(f"Dry-run: would pause sw={sw_hash} lc={lc_hash}", file=sys.stderr)
                print(f"Dry-run: would qbit.set_location({sw_hash}, {new_save})", file=sys.stderr)
                print(f"Dry-run: would qbit.set_category({sw_hash}, calewood)", file=sys.stderr)
                if wait_s:
                    print(f"Dry-run: would sleep {wait_s}s", file=sys.stderr)
                print(f"Dry-run: would qbit.export_torrent_file({sw_hash})", file=sys.stderr)
                print(f"Dry-run: would qbit.export_torrent_file({lc_hash})", file=sys.stderr)
                print(f"Dry-run: would qbit.delete_torrent({lc_hash}, delete_files=False)", file=sys.stderr)
                print(f"Dry-run: would qbit.delete_torrent({sw_hash}, delete_files=False)", file=sys.stderr)
                print(
                    f"Dry-run: would qbit.add_torrent_file(<lacale>, save_path={new_save}, category=calewood, skip_checking=1, start={int(resume_lacale)})",
                    file=sys.stderr,
                )
                print(f"Dry-run: would qbit.add_tag(<lacale_hash>, Moved)", file=sys.stderr)
                print(
                    f"Dry-run: would qbit.add_torrent_file(<sharewood>, save_path={new_save}, category=cross-seed, skip_checking=1, start=0)",
                    file=sys.stderr,
                )
                print(f"Dry-run: would qbit.add_tag(<sharewood_hash>, cross-seed)", file=sys.stderr)
                continue

            try:
                qb.pause_torrents([sw_hash, lc_hash])
            except Exception:  # noqa: BLE001
                # Best-effort; continuing still works but may trigger recheck while paths are inconsistent.
                pass

            try:
                sw_torrent_bytes = qb.export_torrent_file(sw_hash)
                lc_torrent_bytes = qb.export_torrent_file(lc_hash)
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed export .torrent ({name_t}): {e}", file=sys.stderr)
                continue

            try:
                qb.set_location(sw_hash, new_save)
                qb.set_category(sw_hash, "calewood")
                moved += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed move sharewood {sw_hash} ({name_t}): {e}", file=sys.stderr)
                continue

            if wait_move:
                # Wait until qBittorrent reports the move is complete.
                move_timeout = 1800
                started_wait = time.time()
                while True:
                    tcur = qb.get_torrent_by_hash(sw_hash)
                    state = str((tcur or {}).get("state") or "")
                    cur_save = str((tcur or {}).get("save_path") or "").rstrip("/")
                    if state != "moving" and (not cur_save or cur_save == new_save):
                        break
                    if time.time() - started_wait > move_timeout:
                        failed += 1
                        print(
                            f"Timeout waiting for move completion sw={sw_hash} state={state} save_path={cur_save}",
                            file=sys.stderr,
                        )
                        break
                    if args.verbose:
                        elapsed = int(time.time() - started_wait)
                        print(f"Waiting move complete: {elapsed}s state={state} save_path={cur_save}", file=sys.stderr)
                    time.sleep(2)

            if wait_s > 0:
                if args.verbose:
                    print(f"Wait: sleeping {wait_s}s...", file=sys.stderr)
                time.sleep(wait_s)

            try:
                # Remove both torrents without touching data, then re-add them with skip_checking=1 to avoid recheck.
                qb.delete_torrent(lc_hash, delete_files=False)
                qb.delete_torrent(sw_hash, delete_files=False)

                qb.add_torrent_file(
                    lc_torrent_bytes,
                    category="calewood",
                    start=resume_lacale,
                    save_path=new_save,
                    skip_checking=True,
                )
                qb.add_tag(lc_hash, "Moved")

                qb.add_torrent_file(
                    sw_torrent_bytes,
                    category="cross-seed",
                    start=False,
                    save_path=new_save,
                    skip_checking=True,
                )
                qb.add_tag(sw_hash, "cross-seed")
                repointed += 1
                tagged_old += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed re-add pair ({name_t}): {e}", file=sys.stderr)
                continue

        if args.dry_run:
            print(f"Dry-run: would migrate={len(chosen)} candidates_total={len(candidates)} qb_instance={qb_name}", file=sys.stderr)
            return 0

        print(
            f"Done. migrated={moved} repointed={repointed} tagged_old={tagged_old} skipped={skipped} failed={failed} qb_instance={qb_name}",
            file=sys.stderr,
        )
        return 0 if failed == 0 else 1

    if args.qbit_cycle_stop_slow_downloads:
        from collections import deque
        import time

        qb_name, qb = qbit_clients(require_qb_host())[0]
        min_speed_mib = float(args.qbit_cycle_min_speed_mib or 1.0)
        interval_s = int(args.qbit_cycle_interval_seconds or 10)
        probe_s = int(args.qbit_cycle_probe_seconds or 30)
        slots = int(args.qbit_cycle_min_active or 8)
        min_keep = 5
        if min_speed_mib < 0:
            raise RuntimeError("--qbit-cycle-min-speed-mib must be >= 0")
        if interval_s <= 0:
            raise RuntimeError("--qbit-cycle-interval-seconds must be > 0")
        if probe_s <= 0:
            raise RuntimeError("--qbit-cycle-probe-seconds must be > 0")
        if slots <= 0:
            raise RuntimeError("--qbit-cycle-min-active must be > 0")
        if slots < min_keep:
            raise RuntimeError(f"--qbit-cycle-min-active must be >= {min_keep} (got {slots})")

        threshold_bps = int(min_speed_mib * (1024**2))
        # Round-robin pool of paused downloads (FIFO). We guarantee we won't retry the same torrent
        # until we've cycled through everything currently paused.
        paused_rr: deque[str] = deque()
        paused_set: set[str] = set()
        rr_round_seen: set[str] = set()
        # Round window: record downloaded bytes at round start for running torrents.
        round_started_at = 0.0
        round_start_downloaded: dict[str, int] = {}
        tick = 0
        if args.verbose:
            print(
                f"Cycle start: instance={qb_name} interval_s={interval_s} probe_s={probe_s} min_speed_mib={min_speed_mib:.2f} slots={slots}",
                file=sys.stderr,
            )

        try:
            while True:
                tick += 1
                torrents = qb.list_torrents(category=None)
                now_ts = time.time()
                incomplete_running: list[dict] = []
                incomplete_paused: list[dict] = []

                for t in torrents:
                    try:
                        left = int(t.get("amount_left") or 0)
                    except Exception:  # noqa: BLE001
                        left = 0
                    if left <= 0:
                        continue
                    state = str(t.get("state") or "")
                    if state in {"checkingDL", "metaDL"}:
                        continue
                    if state in {"pausedDL", "stoppedDL"}:
                        incomplete_paused.append(t)
                    else:
                        incomplete_running.append(t)

                # Keep the round-robin pool in sync with what is currently paused.
                paused_now: set[str] = set()
                for t in incomplete_paused:
                    h = str(t.get("hash") or "").strip().lower()
                    if not h:
                        continue
                    paused_now.add(h)
                    if h not in paused_set:
                        paused_rr.append(h)
                        paused_set.add(h)

                # Drop hashes that are no longer paused from the RR structures.
                if paused_set:
                    removed = [h for h in list(paused_set) if h not in paused_now]
                    for h in removed:
                        paused_set.discard(h)
                        rr_round_seen.discard(h)
                    if removed:
                        paused_rr = deque([h for h in paused_rr if h in paused_set])

                running_hashes: list[str] = []
                good_running = 0
                for t in incomplete_running:
                    h = str(t.get("hash") or "").strip().lower()
                    if not h:
                        continue
                    running_hashes.append(h)
                    try:
                        speed = int(t.get("dlspeed") or 0)
                    except Exception:  # noqa: BLE001
                        speed = 0
                    if speed >= threshold_bps:
                        good_running += 1

                def rr_next() -> str | None:
                    nonlocal rr_round_seen, paused_rr
                    if not paused_rr:
                        return None
                    if paused_set and rr_round_seen.issuperset(paused_set):
                        rr_round_seen = set()
                    attempts = 0
                    # Strict round-robin across currently paused torrents.
                    while paused_rr and attempts < len(paused_rr) + 1:
                        h0 = paused_rr.popleft()
                        attempts += 1
                        if h0 not in paused_set:
                            continue
                        if h0 in rr_round_seen:
                            paused_rr.append(h0)
                            continue
                        rr_round_seen.add(h0)
                        return h0
                    return None

                # Start a new round if needed.
                if round_started_at <= 0 or (now_ts - round_started_at) >= probe_s:
                    # Evaluate previous round (if any).
                    to_pause: list[str] = []
                    if round_started_at > 0 and round_start_downloaded:
                        # Compute avg speed since round start for torrents still running.
                        avg_list: list[tuple[str, int]] = []
                        below_threshold: list[tuple[str, int]] = []
                        running_set = set(running_hashes)
                        for h, start_dl in round_start_downloaded.items():
                            if h not in running_set:
                                continue
                            t = next((x for x in incomplete_running if str(x.get("hash") or "").strip().lower() == h), None)
                            if not t:
                                continue
                            try:
                                downloaded_now = int(t.get("downloaded") or 0)
                            except Exception:  # noqa: BLE001
                                downloaded_now = start_dl
                            avg_bps = int((max(0, downloaded_now - start_dl)) / max(1e-6, (now_ts - round_started_at)))
                            avg_list.append((h, avg_bps))
                            if avg_bps < threshold_bps:
                                below_threshold.append((h, avg_bps))
                        avg_list.sort(key=lambda x: x[1])  # worst first
                        # Only pause torrents that are below the speed threshold. If the "kept" set is already
                        # fast enough, do nothing and keep the current 8 running.
                        if below_threshold:
                            below_threshold.sort(key=lambda x: x[1])  # worst first
                            max_pause = max(0, min(3, len(running_hashes) - min_keep, len(below_threshold)))
                            for h, avg_bps in below_threshold[:max_pause]:
                                to_pause.append(h)
                                if args.verbose:
                                    print(
                                        f"round pause: hash={h} avg_mib_s={avg_bps/(1024**2):.2f}",
                                        file=sys.stderr,
                                    )
                        elif args.verbose:
                            print(
                                f"round keep: all running avg >= {min_speed_mib:.2f} MiB/s; no cycling",
                                file=sys.stderr,
                            )

                    # After pausing, we will resume up to 3 to reach `slots`.
                    # Note: we decide resumes after applying pauses.
                    running_after_pause = len(running_hashes) - len([h for h in to_pause if h in running_hashes])
                    need = max(0, slots - running_after_pause)
                    to_resume: list[str] = []
                    while need > 0:
                        h = rr_next()
                        if not h:
                            break
                        if h in to_pause:
                            continue
                        to_resume.append(h)
                        need -= 1

                    if args.verbose:
                        print(
                            f"tick={tick} running={len(running_hashes)} good_now={good_running} paused_pool={len(paused_set)} resume={len(to_resume)} pause={len(to_pause)}",
                            file=sys.stderr,
                        )

                    if args.dry_run:
                        if to_resume:
                            print(f"Dry-run: would resume {len(to_resume)} torrents", file=sys.stderr)
                        if to_pause:
                            print(f"Dry-run: would pause {len(to_pause)} torrents", file=sys.stderr)
                    else:
                        if to_pause:
                            qb.pause_torrents(to_pause)
                            qb.bottom_prio(to_pause)
                            for h in to_pause:
                                if h and h not in paused_set:
                                    paused_rr.append(h)
                                    paused_set.add(h)
                        if to_resume:
                            qb.resume_torrents(to_resume)

                    # Begin new round: refresh running set and record start downloaded bytes.
                    round_started_at = time.time()
                    round_start_downloaded = {}
                    refreshed = qb.list_torrents(category=None)
                    for t in refreshed:
                        try:
                            left = int(t.get("amount_left") or 0)
                        except Exception:  # noqa: BLE001
                            left = 0
                        if left <= 0:
                            continue
                        state = str(t.get("state") or "")
                        if state in {"pausedDL", "stoppedDL", "checkingDL", "metaDL"}:
                            continue
                        h = str(t.get("hash") or "").strip().lower()
                        if not h:
                            continue
                        try:
                            downloaded = int(t.get("downloaded") or 0)
                        except Exception:  # noqa: BLE001
                            downloaded = 0
                        round_start_downloaded[h] = downloaded
                else:
                    # Between round evaluations, just print a light heartbeat in verbose.
                    if args.verbose:
                        print(
                            f"tick={tick} (waiting) running={len(running_hashes)} good_now={good_running} paused_pool={len(paused_set)}",
                            file=sys.stderr,
                        )

                time.sleep(interval_s)
        except KeyboardInterrupt:
            if args.verbose:
                print("Cycle stopped (Ctrl-C).", file=sys.stderr)
            return 0

    if args.qbit_stalled_zero_blast:
        from datetime import date

        qbit_list = qbit_clients(require_qb_host())
        qb_name, qb = qbit_list[0]
        torrents = qb.list_torrents(category=None)

        stalled: list[dict] = []
        for t in torrents:
            try:
                left = int(t.get("amount_left") or 0)
            except Exception:  # noqa: BLE001
                left = 0
            if left <= 0:
                continue
            state = str(t.get("state") or "")
            if state in {"queuedDL", "pausedDL", "checkingDL", "metaDL"}:
                continue
            try:
                speed = int(t.get("dlspeed") or 0)
            except Exception:  # noqa: BLE001
                speed = 0
            if speed != 0:
                continue
            stalled.append(t)

        per_page = 200
        blasted = 0
        deleted = 0
        skipped = 0
        skipped_no_hash = 0
        skipped_no_match = 0
        failed = 0
        for t in stalled:
            h = str(t.get("hash") or "").strip().lower()
            if not h:
                skipped += 1
                skipped_no_hash += 1
                continue

            # Find upload by q=hash, then require exact field match.
            upload_id: int | None = None
            try:
                # Limit to my-uploading first (most likely match for stalled downloads).
                resp = calewood.list_uploads(status="my-uploading", q=h, p=1, per_page=per_page)
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed Calewood upload/list?q for {h}: {e}", file=sys.stderr)
                continue
            if not isinstance(resp, dict) or not resp.get("success"):
                failed += 1
                print(f"Calewood upload list failed for {h}: {resp}", file=sys.stderr)
                continue
            items = resp.get("data")
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    sharewood_hash = str(it.get("sharewood_hash") or "").strip().lower()
                    lacale_hash = str(it.get("lacale_hash") or "").strip().lower()
                    if h and (h == sharewood_hash or h == lacale_hash):
                        try:
                            upload_id = int(it.get("id"))
                            break
                        except Exception:  # noqa: BLE001
                            upload_id = None
                            continue

            # Fallback: try all statuses if not found in my-uploading.
            if upload_id is None:
                try:
                    resp2 = calewood.list_uploads(status=None, q=h, p=1, per_page=per_page)
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    print(f"Failed Calewood upload/list(all)?q for {h}: {e}", file=sys.stderr)
                    resp2 = None
                if isinstance(resp2, dict) and resp2.get("success"):
                    items2 = resp2.get("data")
                    if isinstance(items2, list):
                        for it in items2:
                            if not isinstance(it, dict):
                                continue
                            sharewood_hash = str(it.get("sharewood_hash") or "").strip().lower()
                            lacale_hash = str(it.get("lacale_hash") or "").strip().lower()
                            if h and (h == sharewood_hash or h == lacale_hash):
                                try:
                                    upload_id = int(it.get("id"))
                                    break
                                except Exception:  # noqa: BLE001
                                    upload_id = None
                                    continue

            if upload_id is None:
                skipped += 1
                skipped_no_match += 1
                if args.verbose:
                    print(
                        f"Skip blast: no matching upload for hash={h} name={t.get('name')}",
                        file=sys.stderr,
                    )
                continue

            msg = f"[Auto] Blast stalled qBittorrent {qb_name} hash={h} {date.today().isoformat()}"
            try:
                if args.dry_run:
                    print(f"Dry-run: would blast upload {upload_id} ({msg})")
                else:
                    calewood.blast_upload(upload_id, comment=msg)
                    print(f"Blasted upload {upload_id}")
                blasted += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed blast upload {upload_id} hash={h}: {e}", file=sys.stderr)
                continue

            if args.qbit_stalled_zero_delete:
                try:
                    if args.dry_run:
                        print(f"Dry-run: would delete qBittorrent torrent {h} delete_files=1", file=sys.stderr)
                    else:
                        qb.delete_torrent(h, delete_files=True)
                        if args.verbose:
                            print(f"Deleted qBittorrent torrent {h} delete_files=1", file=sys.stderr)
                    deleted += 1
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    print(f"Failed delete qBittorrent torrent {h}: {e}", file=sys.stderr)

        print(
            f"Done. instance={qb_name} stalled={len(stalled)} blasted={blasted} deleted={deleted} skipped={skipped} "
            f"(no_hash={skipped_no_hash} no_match={skipped_no_match}) failed={failed}",
            file=sys.stderr,
        )
        return 0 if failed == 0 else 1

    if args.qbit_stalled_0pct_6h_prearchivage_blast:
        import time

        qbit_list = qbit_clients(require_qb_host())
        qb_name, qb = qbit_list[0]

        # Load "my pre-archiving" list and map hashes -> archive_id.
        per_page = 200
        page = 1
        id_by_hash: dict[str, int] = {}
        total_items = 0
        while True:
            resp = calewood.list_pre_archivage(status="my-pre-archiving", p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood pre-archivage list failed at page {page}: {resp}")
            batch = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(batch, list):
                for it in batch:
                    if not isinstance(it, dict):
                        continue
                    if str(it.get("status") or "").strip() != "pre_archiving":
                        continue
                    try:
                        archive_id = int(it.get("id"))
                    except Exception:  # noqa: BLE001
                        continue
                    total_items += 1
                    sh = str(it.get("sharewood_hash") or it.get("sharewoodHash") or "").strip().lower()
                    lh = str(it.get("lacale_hash") or it.get("lacaleHash") or "").strip().lower()
                    if sh:
                        id_by_hash.setdefault(sh, archive_id)
                    if lh:
                        id_by_hash.setdefault(lh, archive_id)
            if not has_more:
                break
            page += 1

        torrents = qb.list_torrents(category=None)

        now = int(time.time())
        threshold_s = 6 * 3600
        stuck: list[dict] = []
        for t in torrents:
            h = str(t.get("hash") or "").strip().lower()
            if not h or h not in id_by_hash:
                continue
            try:
                left = int(t.get("amount_left") or 0)
            except Exception:  # noqa: BLE001
                left = 0
            if left <= 0:
                continue
            try:
                prog = float(t.get("progress") or 0.0)
            except Exception:  # noqa: BLE001
                prog = 0.0
            if prog != 0.0:
                continue
            state = str(t.get("state") or "")
            if state in {"queuedDL", "pausedDL", "checkingDL", "metaDL"}:
                continue
            try:
                speed = int(t.get("dlspeed") or 0)
            except Exception:  # noqa: BLE001
                speed = 0
            if speed != 0:
                continue
            try:
                added_on = int(t.get("added_on") or 0)
            except Exception:  # noqa: BLE001
                added_on = 0
            if added_on <= 0:
                continue
            age_s = now - added_on
            if age_s < threshold_s:
                continue
            stuck.append(t)

        stuck.sort(key=lambda t: int(t.get("added_on") or 0))
        if args.limit:
            stuck = stuck[: int(args.limit)]

        blasted = 0
        deleted = 0
        skipped = 0
        failed = 0

        for t in stuck:
            h = str(t.get("hash") or "").strip().lower()
            name = str(t.get("name") or "").strip()
            if not h:
                skipped += 1
                continue
            archive_id = id_by_hash.get(h)
            if not archive_id:
                skipped += 1
                continue

            if args.verbose:
                print(f"Blast pre-archivage {archive_id} then delete qBittorrent {h} ({name})", file=sys.stderr)

            if args.dry_run:
                print(f"Dry-run: would POST /api/archive/pre-archivage/blast/{archive_id}")
                print(f"Dry-run: would delete qBittorrent torrent {h} delete_files=1")
                continue

            try:
                calewood.blast_pre_archivage(archive_id, comment=None)
                blasted += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed Calewood pre-archivage blast {archive_id} ({name}): {e}", file=sys.stderr)
                continue

            try:
                qb.delete_torrent(h, delete_files=True)
                deleted += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed qBittorrent delete {h} ({name}): {e}", file=sys.stderr)

        print(
            f"Done. instance={qb_name} my_pre_archiving={total_items} stuck={len(stuck)} blasted={blasted} deleted={deleted} skipped={skipped} failed={failed}",
            file=sys.stderr,
        )
        return 0 if failed == 0 else 1

    if args.qbit_stalled_4h_prearchivage_blast:
        import time

        qbit_list = qbit_clients(require_qb_host())
        qb_name, qb = qbit_list[0]

        # Load my pre-archiving list (pre_archiving only) and map hashes -> archive_id.
        per_page = 200
        page = 1
        id_by_hash: dict[str, int] = {}
        total_items = 0
        while True:
            resp = calewood.list_pre_archivage(status="my-pre-archiving", p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood pre-archivage list failed at page {page}: {resp}")
            batch = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(batch, list):
                for it in batch:
                    if not isinstance(it, dict):
                        continue
                    if str(it.get("status") or "").strip() != "pre_archiving":
                        continue
                    try:
                        archive_id = int(it.get("id"))
                    except Exception:  # noqa: BLE001
                        continue
                    total_items += 1
                    sh = str(it.get("sharewood_hash") or it.get("sharewoodHash") or "").strip().lower()
                    lh = str(it.get("lacale_hash") or it.get("lacaleHash") or "").strip().lower()
                    if sh:
                        id_by_hash.setdefault(sh, archive_id)
                    if lh:
                        id_by_hash.setdefault(lh, archive_id)
            if not has_more:
                break
            page += 1

        torrents = qb.list_torrents(category=None)

        now = int(time.time())
        threshold_s = 4 * 3600
        stuck: list[dict] = []
        for t in torrents:
            h = str(t.get("hash") or "").strip().lower()
            if not h or h not in id_by_hash:
                continue
            try:
                left = int(t.get("amount_left") or 0)
            except Exception:  # noqa: BLE001
                left = 0
            if left <= 0:
                continue
            state = str(t.get("state") or "")
            if state in {"queuedDL", "pausedDL", "checkingDL", "metaDL"}:
                continue
            try:
                speed = int(t.get("dlspeed") or 0)
            except Exception:  # noqa: BLE001
                speed = 0
            if speed != 0:
                continue
            # Prefer last_activity (more meaningful), fallback to added_on.
            try:
                last_activity = int(t.get("last_activity") or 0)
            except Exception:  # noqa: BLE001
                last_activity = 0
            try:
                added_on = int(t.get("added_on") or 0)
            except Exception:  # noqa: BLE001
                added_on = 0
            ref = last_activity if last_activity > 0 else added_on
            if ref <= 0:
                continue
            age_s = now - ref
            if age_s < threshold_s:
                continue
            stuck.append(t)

        stuck.sort(key=lambda t: int(t.get("last_activity") or t.get("added_on") or 0))
        if args.limit:
            stuck = stuck[: int(args.limit)]

        blasted = 0
        deleted = 0
        skipped = 0
        failed = 0

        for t in stuck:
            h = str(t.get("hash") or "").strip().lower()
            name = str(t.get("name") or "").strip()
            archive_id = id_by_hash.get(h)
            if not h or not archive_id:
                skipped += 1
                continue

            if args.verbose:
                prog = t.get("progress")
                la = t.get("last_activity")
                ao = t.get("added_on")
                print(
                    f"Blast pre-archivage {archive_id} then delete qBittorrent {h} progress={prog} last_activity={la} added_on={ao} ({name})",
                    file=sys.stderr,
                )

            if args.dry_run:
                print(f"Dry-run: would POST /api/archive/pre-archivage/blast/{archive_id}")
                print(f"Dry-run: would delete qBittorrent torrent {h} delete_files=1")
                continue

            try:
                calewood.blast_pre_archivage(archive_id, comment=None)
                blasted += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed Calewood pre-archivage blast {archive_id} ({name}): {e}", file=sys.stderr)
                continue

            try:
                qb.delete_torrent(h, delete_files=True)
                deleted += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed qBittorrent delete {h} ({name}): {e}", file=sys.stderr)

        print(
            f"Done. instance={qb_name} my_pre_archiving={total_items} stuck={len(stuck)} blasted={blasted} deleted={deleted} skipped={skipped} failed={failed}",
            file=sys.stderr,
        )
        return 0 if failed == 0 else 1

    if args.seedbox_upload_prearchivage_flow:
        # 1) Trigger seedbox verification for uploads.
        passphrase = seedbox_passphrase_required()
        # Even in dry-run, we still trigger the seedbox check (user request).
        calewood.seedbox_check_uploads(passphrase=passphrase)
        if args.verbose:
            print('Triggered /api/upload/seedbox-check {"passphrase":"***"}', file=sys.stderr)

        # 2) List my-uploading and pick those fully complete on seedbox.
        per_page = 200
        page = 1
        ready: list[dict] = []
        while True:
            resp = calewood.list_uploads(status="my-uploading", p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood upload list failed at page {page}: {resp}")
            items = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    prog = it.get("seedbox_progress")
                    if prog in (1, 1.0, "1", "1.0", True):
                        ready.append(it)
            if not has_more:
                break
            page += 1

        # 3) For each ready item, run the requested POST sequence.
        moved = 0
        skipped = 0
        failed = 0
        limit_n = int(args.seedbox_upload_prearchivage_limit or 0)
        for it in ready:
            if limit_n > 0 and moved >= limit_n:
                break
            try:
                tid = int(it.get("id"))
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
            name = str(it.get("name", "") or "").strip()
            if args.verbose:
                print(f"Ready seedbox_progress=1 id={tid} name={name}", file=sys.stderr)
            try:
                if args.dry_run:
                    print(f"Dry-run: would POST /api/upload/abandon/{tid}")
                    print(f"Dry-run: would POST /api/archive/pre-archivage/take/{tid}")
                    print(f"Dry-run: would POST /api/archive/pre-archivage/dl-done/{tid}")
                else:
                    calewood.abandon_upload(tid)
                    calewood.take_pre_archivage(tid)
                    calewood.dl_done_pre_archivage(tid)
                    print(f"Moved to pre-archivage: {tid} {name}")
                moved += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed flow for {tid} ({name}): {e}", file=sys.stderr)

        print(f"Done. ready={len(ready)} moved={moved} skipped={skipped} failed={failed}", file=sys.stderr)
        return 0 if failed == 0 else 1

    if args.list_my_upload_prearchivage:
        per_page = 200
        page = 1
        items_all: list[dict] = []
        while True:
            resp = calewood.list_upload_pre_archivage(status="my-fiches", p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood upload/pre-archivage list failed at page {page}: {resp}")
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

        if args.json:
            for it in items_all:
                print(json.dumps(it, ensure_ascii=False))
            print(f"count={len(items_all)}", file=sys.stderr)
            return 0

        def clip(s: str, n: int) -> str:
            s = s or ""
            return s if len(s) <= n else s[: n - 1] + "…"

        headers = ("ID", "SIZE", "SUBCAT", "NAME")
        rows: list[tuple[str, str, str, str]] = []
        for it in items_all:
            rows.append(
                (
                    str(it.get("id", "")),
                    clip(str(it.get("size_raw", "") or ""), 10),
                    clip(str(it.get("subcategory", "") or ""), 16),
                    clip(str(it.get("name", "") or ""), 80),
                )
            )
        widths = [len(h) for h in headers]
        for r in rows:
            for i, c in enumerate(r):
                widths[i] = max(widths[i], len(c))
        print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
        print("  ".join(("-" * widths[i]) for i in range(len(headers))))
        for r in rows:
            print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))))
        print(f"\ncount={len(items_all)}", file=sys.stderr)
        return 0

    if args.list_my_archive_prearchivage:
        # Refresh seedbox progress for archives so we can display it.
        if args.verbose:
            print("Triggering /api/archive/seedbox-check", file=sys.stderr)
        calewood.seedbox_check_archives(passphrase=seedbox_passphrase_required())

        per_page = 200
        page = 1
        items_all: list[dict] = []
        while True:
            resp = calewood.list_pre_archivage(status="my-pre-archiving", p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood archive/pre-archivage list failed at page {page}: {resp}")
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

        if args.json:
            for it in items_all:
                print(json.dumps(it, ensure_ascii=False))
            print(f"count={len(items_all)}", file=sys.stderr)
            return 0

        def clip(s: str, n: int) -> str:
            s = s or ""
            return s if len(s) <= n else s[: n - 1] + "…"

        def fmt_prog(v: object) -> str:
            if v in (None, "", "null"):
                return ""
            try:
                f = float(v)  # can be 0..1
                if f > 1:
                    # sometimes API could return 0..100
                    f = f / 100.0
                return f"{(f * 100):.0f}%"
            except Exception:  # noqa: BLE001
                return str(v)

        dl_done = 0
        dl_done_failed = 0

        headers = ("ID", "STATUS", "PROG", "SIZE", "NAME")
        rows: list[tuple[str, str, str, str, str]] = []
        for it in items_all:
            prog_raw = it.get("seedbox_progress")
            prog_str = fmt_prog(prog_raw)
            is_100 = prog_raw in (1, 1.0, "1", "1.0", True) or prog_str == "100%"

            if args.list_my_archive_prearchivage_dl_done and is_100:
                try:
                    archive_id = int(it.get("id"))
                except Exception:  # noqa: BLE001
                    archive_id = -1
                if archive_id > 0:
                    try:
                        if args.dry_run:
                            if args.verbose:
                                print(f"Dry-run: would POST /api/archive/pre-archivage/dl-done/{archive_id}", file=sys.stderr)
                        else:
                            calewood.dl_done_pre_archivage(archive_id)
                            if args.verbose:
                                print(f"dl-done {archive_id}", file=sys.stderr)
                        dl_done += 1
                    except Exception as e:  # noqa: BLE001
                        dl_done_failed += 1
                        print(f"Failed dl-done {archive_id}: {e}", file=sys.stderr)

            rows.append(
                (
                    str(it.get("id", "")),
                    clip(str(it.get("status", "") or ""), 18),
                    prog_str,
                    clip(str(it.get("size_raw", "") or ""), 10),
                    clip(str(it.get("name", "") or ""), 80),
                )
            )
        widths = [len(h) for h in headers]
        for r in rows:
            for i, c in enumerate(r):
                widths[i] = max(widths[i], len(c))
        print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
        print("  ".join(("-" * widths[i]) for i in range(len(headers))))
        for r in rows:
            print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))))
        print(f"\ncount={len(items_all)} dl_done={dl_done} dl_done_failed={dl_done_failed}", file=sys.stderr)
        return 0

    if args.prearchivage_dl_done_100:
        # Compare my pre_archiving items with the provided qBittorrent host.
        qb = qbit_clients(require_qb_host())[0][1]

        per_page = 200
        page = 1
        items_all: list[dict] = []
        while True:
            # Only my pre-archiving queue.
            resp = calewood.list_pre_archivage(status="my-pre-archiving", p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood archive/pre-archivage list failed at page {page}: {resp}")
            batch = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(batch, list):
                for it in batch:
                    if not isinstance(it, dict):
                        continue
                    if str(it.get("status") or "").strip() != "pre_archiving":
                        continue
                    items_all.append(it)
            if not has_more:
                break
            page += 1

        # Bulk check which hashes exist in qBittorrent.
        id_by_hash: dict[str, int] = {}
        for it in items_all:
            try:
                aid = int(it.get("id"))
            except Exception:  # noqa: BLE001
                continue
            sh = str(it.get("sharewood_hash") or it.get("sharewoodHash") or "").strip().lower()
            if sh:
                id_by_hash[sh] = aid

        torrents_map = qb.torrents_by_hashes(list(id_by_hash.keys()))

        done = 0
        failed = 0
        skipped = 0
        matched = 0
        complete = 0
        missing_in_qbit = 0
        no_hash = 0
        for it in items_all:
            try:
                archive_id = int(it.get("id"))
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
            name = str(it.get("name", "") or "").strip()
            sh = str(it.get("sharewood_hash") or it.get("sharewoodHash") or "").strip().lower()
            if not sh:
                no_hash += 1
                if args.verbose:
                    print(f"Skip no sharewood_hash: {archive_id} ({name})", file=sys.stderr)
                skipped += 1
                continue
            matched += 1
            t = torrents_map.get(sh)
            if not t:
                missing_in_qbit += 1
                if args.verbose:
                    print(f"Missing in qBittorrent: {archive_id} hash={sh} ({name})", file=sys.stderr)
                skipped += 1
                continue
            try:
                prog = float(t.get("progress") or 0.0)
            except Exception:  # noqa: BLE001
                prog = 0.0
            if prog < 0.999:
                if args.verbose:
                    print(f"Not complete in qBittorrent: {archive_id} hash={sh} progress={prog:.3f} ({name})", file=sys.stderr)
                skipped += 1
                continue
            complete += 1
            try:
                if args.dry_run:
                    print(f"Dry-run: would POST /api/archive/pre-archivage/dl-done/{archive_id}")
                else:
                    calewood.dl_done_pre_archivage(archive_id)
                    if args.verbose:
                        print(f"dl-done {archive_id}: {name}", file=sys.stderr)
                done += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed dl-done {archive_id} ({name}): {e}", file=sys.stderr)

        print(
            f"Done. targets={len(items_all)} matched={matched} complete_in_qbit={complete} missing_in_qbit={missing_in_qbit} "
            f"no_hash={no_hash} done={done} skipped={skipped} failed={failed}",
            file=sys.stderr,
        )
        return 0 if failed == 0 else 1

    if args.prearchivage_take is not None:
        tid = int(args.prearchivage_take)
        if args.dry_run:
            print(f"Dry-run: would POST /api/archive/pre-archivage/take/{tid}")
        else:
            calewood.take_pre_archivage(tid)
            print(f"Took pre-archivage {tid}")
        return 0

    if args.prearchivage_abandon is not None:
        tid = int(args.prearchivage_abandon)
        if args.dry_run:
            print(f"Dry-run: would POST /api/archive/pre-archivage/abandon/{tid}")
        else:
            calewood.abandon_pre_archivage(tid)
            print(f"Abandoned pre-archivage {tid}")
        return 0

    if args.prearchivage_confirm is not None:
        tid = int(args.prearchivage_confirm)
        if args.dry_run:
            print(f"Dry-run: would POST /api/archive/pre-archivage/confirm/{tid}")
        else:
            calewood.confirm_pre_archivage(tid)
            print(f"Confirmed pre-archivage {tid}")
        return 0

    if args.prearchivage_blast is not None:
        tid = int(args.prearchivage_blast)
        comment = str(args.prearchivage_blast_comment or "").strip()
        if args.dry_run:
            print(f"Dry-run: would POST /api/archive/pre-archivage/blast/{tid} comment={comment!r}")
        else:
            calewood.blast_pre_archivage(tid, comment=comment or None)
            print(f"Blasted pre-archivage {tid}")
        return 0

    if args.prearchivage_torrent_file is not None:
        tid = int(args.prearchivage_torrent_file)
        out = str(args.prearchivage_torrent_file_out or "").strip()
        if not out:
            raise RuntimeError("--prearchivage-torrent-file-out is required.")
        data = calewood.download_pre_archivage_torrent_file(tid)
        Path(out).write_bytes(data)
        print(out)
        return 0

    if args.prearchivage_take_smallest is not None:
        n = int(args.prearchivage_take_smallest)
        if n <= 0:
            raise RuntimeError("N must be > 0")
        out_dir = str(args.prearchivage_torrent_dir or "").strip()
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        qb = None
        if args.prearchivage_add_to_qbit:
            qb = qbit_clients(require_qb_host())[0][1]

        per_page = 200
        page = 1
        available: list[dict] = []
        q = str(args.prearchivage_q or "").strip() or None
        cat = str(args.prearchivage_cat or "").strip() or None
        subcat = str(args.prearchivage_subcat or "").strip() or None
        seeders = int(args.prearchivage_seeders or 0) or None
        min_size = str(args.prearchivage_min_size or "").strip() or None
        max_size = str(args.prearchivage_max_size or "").strip() or None
        while True:
            resp = calewood.list_pre_archivage(
                q=q,
                cat=cat,
                subcat=subcat,
                seeders=seeders,
                min_size=min_size,
                max_size=max_size,
                p=page,
                per_page=per_page,
            )
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood pre-archivage list failed at page {page}: {resp}")
            batch = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(batch, list):
                for it in batch:
                    if isinstance(it, dict):
                        available.append(it)
            if not has_more:
                break
            page += 1

        available.sort(key=lambda it: int(it.get("size_bytes") or 0))
        chosen = available[:n]

        took = 0
        downloaded = 0
        failed = 0
        for it in chosen:
            try:
                tid = int(it.get("id"))
            except Exception:  # noqa: BLE001
                failed += 1
                continue
            name = str(it.get("name", "") or "").strip()
            if args.verbose:
                print(f"Pick {tid} size_bytes={int(it.get('size_bytes') or 0)} name={name}", file=sys.stderr)
            try:
                if args.dry_run:
                    print(f"Dry-run: would POST /api/archive/pre-archivage/take/{tid}")
                    print(f"Dry-run: would GET /api/archive/pre-archivage/torrent-file/{tid} -> {out_path / (str(tid) + '.torrent')}")
                    if args.prearchivage_add_to_qbit:
                        print(f'Dry-run: would add to qBittorrent category="sharewood" start=1')
                else:
                    calewood.take_pre_archivage(tid)
                    took += 1
                    data = calewood.download_pre_archivage_torrent_file(tid)
                    dest = out_path / f"{tid}.torrent"
                    dest.write_bytes(data)
                    downloaded += 1
                    if qb is not None:
                        qb.add_torrent_file(data, category="sharewood", start=True)
                    print(str(dest))
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed take/download {tid} ({name}): {e}", file=sys.stderr)

        print(
            f"Done. available={len(available)} chosen={len(chosen)} took={took} downloaded={downloaded} failed={failed}",
            file=sys.stderr,
        )
        return 0 if failed == 0 else 1

    if args.prearchivage_download_my_torrents or args.prearchivage_download_my_awaiting_fiche_torrents:
        only_awaiting_fiche = bool(args.prearchivage_download_only_awaiting_fiche or args.prearchivage_download_my_awaiting_fiche_torrents)
        out_dir = str(args.prearchivage_torrent_dir or "").strip()
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        qb = None
        if args.prearchivage_add_to_qbit:
            qb = qbit_clients(require_qb_host())[0][1]

        def _bdecode(data: bytes, idx: int = 0):
            if idx >= len(data):
                raise ValueError("bdecode: out of range")
            c = data[idx : idx + 1]
            if c == b"i":
                end = data.index(b"e", idx)
                return int(data[idx + 1 : end]), end + 1
            if c == b"l":
                idx += 1
                out = []
                while data[idx : idx + 1] != b"e":
                    v, idx = _bdecode(data, idx)
                    out.append(v)
                return out, idx + 1
            if c == b"d":
                idx += 1
                out = {}
                while data[idx : idx + 1] != b"e":
                    k, idx = _bdecode(data, idx)
                    v, idx = _bdecode(data, idx)
                    out[k] = v
                return out, idx + 1
            # bytes: <len>:<payload>
            if b"0" <= c <= b"9":
                colon = data.index(b":", idx)
                ln = int(data[idx:colon])
                start = colon + 1
                end = start + ln
                return data[start:end], end
            raise ValueError(f"bdecode: unexpected byte {c!r} at {idx}")

        def _bencode(x) -> bytes:
            if isinstance(x, int):
                return b"i" + str(x).encode("ascii") + b"e"
            if isinstance(x, (bytes, bytearray)):
                b = bytes(x)
                return str(len(b)).encode("ascii") + b":" + b
            if isinstance(x, str):
                b = x.encode("utf-8")
                return str(len(b)).encode("ascii") + b":" + b
            if isinstance(x, list):
                return b"l" + b"".join(_bencode(v) for v in x) + b"e"
            if isinstance(x, dict):
                # keys must be sorted lexicographically (bytes)
                items = []
                for k in sorted(x.keys(), key=lambda k: k if isinstance(k, (bytes, bytearray)) else str(k).encode("utf-8")):
                    items.append(_bencode(k))
                    items.append(_bencode(x[k]))
                return b"d" + b"".join(items) + b"e"
            raise TypeError(f"bencode: unsupported type {type(x)}")

        def _torrent_infohash_v1(torrent_bytes: bytes) -> str | None:
            import hashlib

            try:
                root, end = _bdecode(torrent_bytes, 0)
                if end != len(torrent_bytes):
                    # trailing bytes are unusual but ignore
                    pass
                if not isinstance(root, dict):
                    return None
                info = root.get(b"info") or root.get("info")
                if not isinstance(info, dict):
                    return None
                info_enc = _bencode(info)
                return hashlib.sha1(info_enc).hexdigest()
            except Exception:  # noqa: BLE001
                return None

        per_page = 200
        page = 1
        items: list[dict] = []
        while True:
            resp = calewood.list_pre_archivage(status="my-pre-archiving", p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood archive/pre-archivage list failed at page {page}: {resp}")
            batch = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(batch, list):
                for it in batch:
                    if isinstance(it, dict):
                        items.append(it)
            if not has_more:
                break
            page += 1

        wanted_statuses = {"pre_archiving", "awaiting_fiche", "post_archiving"}
        items = [it for it in items if str(it.get("status") or "").strip() in wanted_statuses]
        if args.prearchivage_download_only_pre_archiving:
            items = [it for it in items if str(it.get("status") or "").strip() == "pre_archiving"]
        if only_awaiting_fiche:
            items = [it for it in items if str(it.get("status") or "").strip() == "awaiting_fiche"]

        # If pushing to qBittorrent, compute a diff first and only process items missing in qBittorrent.
        # For Sharewood .torrent downloads, only sharewood_hash is relevant (lacale_hash may be absent/unknown here).
        if qb is not None and items:
            wanted_hashes: list[str] = []
            for it in items:
                sh = str(it.get("sharewood_hash") or it.get("sharewoodHash") or "").strip().lower()
                if sh:
                    wanted_hashes.append(sh)

            present: set[str] = set()
            chunk_size = 100
            for i in range(0, len(wanted_hashes), chunk_size):
                chunk = wanted_hashes[i : i + chunk_size]
                try:
                    m = qb.torrents_by_hashes(chunk)
                except Exception:  # noqa: BLE001
                    m = {}
                for h in m.keys():
                    present.add(str(h).lower())

            before = len(items)
            kept: list[dict] = []
            for it in items:
                sh = str(it.get("sharewood_hash") or it.get("sharewoodHash") or "").strip().lower()
                if not sh:
                    kept.append(it)
                    continue
                if sh not in present:
                    kept.append(it)
            items = kept
            if args.verbose:
                print(f"Diff pre-archivage vs qBittorrent: total={before} present={before - len(items)} missing={len(items)}", file=sys.stderr)

        if args.limit:
            items = items[: int(args.limit)]

        downloaded = 0
        added = 0
        skipped = 0
        failed = 0
        for it in items:
            try:
                tid = int(it.get("id"))
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
            name = str(it.get("name", "") or "").strip()
            dest = out_path / f"{tid}.torrent"

            if args.verbose:
                print(f"Download .torrent {tid} status={it.get('status')} -> {dest} name={name}", file=sys.stderr)

            try:
                # If we already downloaded this .torrent and it's already in qBittorrent, skip.
                if qb is not None and dest.exists():
                    ih = _torrent_infohash_v1(dest.read_bytes())
                    if ih:
                        try:
                            already = qb.get_torrent_by_hash(ih)
                        except Exception:  # noqa: BLE001
                            already = None
                        if already is not None:
                            skipped += 1
                            if args.verbose:
                                print(f"Skip already in qBittorrent: id={tid} infohash={ih} name={name}", file=sys.stderr)
                            continue

                if args.dry_run:
                    print(f"Dry-run: would GET /api/archive/pre-archivage/torrent-file/{tid} -> {dest}")
                    if qb is not None:
                        print('Dry-run: would add to qBittorrent category="sharewood" start=1')
                    continue

                try:
                    data = calewood.download_pre_archivage_torrent_file(tid)
                except Exception as e:  # noqa: BLE001
                    # If the torrent file is missing (404), abandon it so it can be retried later by someone else.
                    msg = str(e)
                    if "HTTP 404" in msg or "404 Not Found" in msg:
                        if args.verbose:
                            print(
                                f"torrent-file 404 for {tid} ({name}) → abandon /api/archive/pre-archivage/abandon/{tid}",
                                file=sys.stderr,
                            )
                        if args.dry_run:
                            print(f"Dry-run: would POST /api/archive/pre-archivage/abandon/{tid}")
                        else:
                            calewood.abandon_pre_archivage(tid)
                        skipped += 1
                        continue
                    raise
                dest.write_bytes(data)
                downloaded += 1
                print(str(dest))

                if qb is not None:
                    qb.add_torrent_file(data, category="sharewood", start=True)
                    added += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed download/add {tid} ({name}): {e}", file=sys.stderr)

        print(
            f"Done. items={len(items)} downloaded={downloaded} added_to_qbit={added} skipped={skipped} failed={failed}",
            file=sys.stderr,
        )
        return 0 if failed == 0 else 1

    if args.prearchivage_verify_my_awaiting_fiche_100 or args.prearchivage_redl_my_awaiting_fiche_not_complete:
        qb_name, qb = qbit_clients(require_qb_host())[0]
        per_page = 200
        page = 1
        items: list[dict] = []
        while True:
            resp = calewood.list_pre_archivage(status="my-pre-archiving", p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood archive/pre-archivage list failed at page {page}: {resp}")
            batch = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(batch, list):
                for it in batch:
                    if isinstance(it, dict) and str(it.get("status") or "").strip() == "awaiting_fiche":
                        items.append(it)
            if not has_more:
                break
            page += 1

        wanted_hashes: list[str] = []
        for it in items:
            sh = str(it.get("sharewood_hash") or it.get("sharewoodHash") or "").strip().lower()
            if sh:
                wanted_hashes.append(sh)

        present: dict[str, dict] = {}
        chunk_size = 100
        for i in range(0, len(wanted_hashes), chunk_size):
            chunk = wanted_hashes[i : i + chunk_size]
            try:
                m = qb.torrents_by_hashes(chunk)
            except Exception:  # noqa: BLE001
                m = {}
            for h, t in m.items():
                present[str(h).lower()] = t

        missing = 0
        not_complete = 0
        ok = 0
        redl_targets: list[dict] = []

        def clip(s: str, n: int) -> str:
            s = s or ""
            return s if len(s) <= n else s[: n - 1] + "…"

        rows: list[tuple[str, str, str, str]] = []
        for it in sorted(items, key=lambda x: int(x.get("size_bytes") or 0), reverse=True):
            tid = str(it.get("id") or "")
            name = clip(str(it.get("name") or ""), 80)
            sh = str(it.get("sharewood_hash") or it.get("sharewoodHash") or "").strip().lower()
            if not sh:
                rows.append((tid, "?", "no_hash", name))
                missing += 1
                redl_targets.append(it)
                continue
            t = present.get(sh)
            if not t:
                rows.append((tid, sh[:12], "missing", name))
                missing += 1
                redl_targets.append(it)
                continue
            try:
                prog = float(t.get("progress") or 0.0)
            except Exception:  # noqa: BLE001
                prog = 0.0
            if prog >= 0.999999:
                rows.append((tid, sh[:12], "ok", name))
                ok += 1
            else:
                rows.append((tid, sh[:12], f"{prog*100:.2f}%", name))
                not_complete += 1
                redl_targets.append(it)

        headers = ("ID", "SH_HASH", "STATE", "NAME")
        widths = [len(h) for h in headers]
        for r in rows:
            for i, c in enumerate(r):
                widths[i] = max(widths[i], len(c))
        print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
        print("  ".join(("-" * widths[i]) for i in range(len(headers))))
        for r in rows:
            print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))))

        print(
            f"\nawaiting_fiche total={len(items)} ok={ok} not_complete={not_complete} missing={missing} qb_instance={qb_name}",
            file=sys.stderr,
        )
        if args.prearchivage_redl_my_awaiting_fiche_not_complete:
            out_dir = str(args.prearchivage_torrent_dir or "").strip()
            out_path = Path(out_dir)
            out_path.mkdir(parents=True, exist_ok=True)

            limit = int(args.limit or 0)
            if limit <= 0:
                limit = 1
            targets = redl_targets[:limit]
            redownloaded = 0
            deleted = 0
            added = 0
            failed = 0
            for it in targets:
                try:
                    tid_i = int(it.get("id"))
                except Exception:  # noqa: BLE001
                    failed += 1
                    continue
                sh = str(it.get("sharewood_hash") or it.get("sharewoodHash") or "").strip().lower()
                name_i = str(it.get("name") or "")
                dest = out_path / (f"{tid_i}_{sh}.torrent" if sh else f"{tid_i}.torrent")
                if args.verbose:
                    print(f"Redl awaiting_fiche {tid_i} sharewood_hash={sh} -> {dest} name={name_i}", file=sys.stderr)

                # If present but incomplete, delete with files first.
                if sh and sh in present:
                    try:
                        prog = float(present[sh].get("progress") or 0.0)
                    except Exception:  # noqa: BLE001
                        prog = 0.0
                    if prog < 0.999999:
                        if args.dry_run:
                            print(f"Dry-run: would delete torrent+files {sh} from qBittorrent({qb_name})", file=sys.stderr)
                        else:
                            try:
                                qb.delete_torrent(sh, delete_files=True)
                                deleted += 1
                            except Exception as e:  # noqa: BLE001
                                failed += 1
                                print(f"Failed delete {sh} ({name_i}): {e}", file=sys.stderr)
                                continue

                if args.dry_run:
                    print(f"Dry-run: would GET /api/archive/pre-archivage/torrent-file/{tid_i} -> {dest}", file=sys.stderr)
                    print(f'Dry-run: would add to qBittorrent({qb_name}) category="sharewood" start=1', file=sys.stderr)
                    continue

                try:
                    data = calewood.download_pre_archivage_torrent_file(tid_i)
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    print(f"Failed download pre-archivage torrent-file {tid_i} ({name_i}): {e}", file=sys.stderr)
                    continue
                try:
                    dest.write_bytes(data)
                    redownloaded += 1
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    print(f"Failed write {dest}: {e}", file=sys.stderr)
                    continue
                try:
                    qb.add_torrent_file(data, category="sharewood", start=True)
                    added += 1
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    print(f"Failed add to qBittorrent({qb_name}) id={tid_i}: {e}", file=sys.stderr)
                    continue
                print(str(dest))

            if args.dry_run:
                print(f"Dry-run: would redl={len(targets)} qb_instance={qb_name}", file=sys.stderr)
                return 0
            print(
                f"Done. targets={len(targets)} redownloaded={redownloaded} deleted={deleted} added_to_qbit={added} failed={failed} qb_instance={qb_name}",
                file=sys.stderr,
            )
            return 0 if failed == 0 else 1

        return 0 if (missing == 0 and not_complete == 0) else 2

    if args.prearchivage_confirm_my_post_archiving_100:
        import shutil
        import subprocess

        qb = qbit_clients(require_qb_host())[0][1]
        opener = shutil.which("xdg-open") or shutil.which("open") or shutil.which("start")
        torrent_dir = str(getattr(args, "prearchivage_download_sharewood_torrent_dir", "") or "").strip()
        # Accept the global --download-sharewood-torrent-dir as an alias for this command too.
        if not torrent_dir:
            torrent_dir = str(getattr(args, "download_sharewood_torrent_dir", "") or "").strip()
        torrent_path = Path(torrent_dir) if torrent_dir else None
        if torrent_path is not None:
            torrent_path.mkdir(parents=True, exist_ok=True)

        calewood.seedbox_check_archives(passphrase=seedbox_passphrase_required())
        if args.verbose:
            print("Triggered /api/archive/seedbox-check", file=sys.stderr)

        per_page = 200
        page = 1
        mine_items: list[dict] = []
        targets: list[dict] = []
        while True:
            resp = calewood.list_pre_archivage(status="my-pre-archiving", p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood archive/pre-archivage list failed at page {page}: {resp}")
            batch = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(batch, list):
                for it in batch:
                    if not isinstance(it, dict):
                        continue
                    mine_items.append(it)
                    if str(it.get("status") or "").strip() != "post_archiving":
                        continue
                    prog = it.get("seedbox_progress")
                    is_100 = False
                    # Seedbox progress is often absent/irrelevant once in post_archiving.
                    if str(it.get("status") or "").strip() == "post_archiving":
                        is_100 = True
                    elif prog in (1, 1.0, "1", "1.0", True, 100, "100", "100.0"):
                        is_100 = True
                    else:
                        try:
                            f = float(prog)
                            if f > 1:
                                f = f / 100.0
                            is_100 = f >= 0.999
                        except Exception:  # noqa: BLE001
                            is_100 = False
                    if is_100:
                        targets.append(it)
            if not has_more:
                break
            page += 1

        if args.verbose and not targets:
            # Help debugging: show status distribution for mine=1 list.
            by_status: dict[str, int] = {}
            for it in mine_items:
                s = str(it.get("status") or "").strip() or "<empty>"
                by_status[s] = by_status.get(s, 0) + 1
            dist = ", ".join([f"{k}={v}" for k, v in sorted(by_status.items(), key=lambda kv: kv[0])])
            print(f"pre-archivage mine=1 status_counts: {dist}", file=sys.stderr)

        confirmed = 0
        missing_in_qbit = 0
        opened = 0
        failed = 0
        skipped = 0
        missing_no_hash = 0
        unknown_lacale_rows: list[tuple[str, str, str]] = []
        for it in targets:
            try:
                archive_id = int(it.get("id"))
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
            name = str(it.get("name", "") or "").strip()
            lacale_hash = str(it.get("lacale_hash", "") or "").strip().lower()
            try:
                if lacale_hash:
                    try:
                        t = qb.get_torrent_by_hash(lacale_hash)
                    except Exception:  # noqa: BLE001
                        t = None
                    present = bool(t) and (t.get("progress") in (1, 1.0))
                else:
                    present = False

                if not present:
                    if not lacale_hash:
                        missing_no_hash += 1
                        sh = str(it.get("sharewood_hash") or it.get("sharewoodHash") or "").strip().lower()
                        unknown_lacale_rows.append((str(archive_id), sh, name))
                        if args.verbose:
                            print(
                                f"Missing lacale_hash for post_archiving item: {archive_id} ({name}) → cannot open La-Cale download URL",
                                file=sys.stderr,
                            )
                        if torrent_path is not None:
                            fname_hash = (sh or "").lower() if sh else ""
                            suffix = f"_{fname_hash}" if fname_hash else ""
                            dest = torrent_path / f"{archive_id}{suffix}.torrent"
                            if args.verbose:
                                print(f"Download Sharewood .torrent {archive_id} -> {dest}", file=sys.stderr)
                            if args.dry_run:
                                print(f"Dry-run: would GET /api/archive/pre-archivage/torrent-file/{archive_id} -> {dest}", file=sys.stderr)
                            else:
                                try:
                                    data = calewood.download_pre_archivage_torrent_file(archive_id)
                                    dest.write_bytes(data)
                                except Exception as e:  # noqa: BLE001
                                    print(f"Failed download Sharewood .torrent for {archive_id}: {e}", file=sys.stderr)
                        continue
                    missing_in_qbit += 1
                    url = f"https://la-cale.space/api/torrents/download/{lacale_hash}"
                    if args.verbose:
                        print(f"Missing in qBittorrent: {archive_id} hash={lacale_hash} → open {url}", file=sys.stderr)
                    if torrent_path is not None:
                        sh = str(it.get("sharewood_hash") or it.get("sharewoodHash") or "").strip().lower()
                        suffix = f"_{sh}" if sh else ""
                        dest = torrent_path / f"{archive_id}{suffix}.torrent"
                        if args.verbose:
                            print(f"Download Sharewood .torrent {archive_id} -> {dest}", file=sys.stderr)
                        if args.dry_run:
                            print(f"Dry-run: would GET /api/archive/pre-archivage/torrent-file/{archive_id} -> {dest}", file=sys.stderr)
                        else:
                            try:
                                data = calewood.download_pre_archivage_torrent_file(archive_id)
                                dest.write_bytes(data)
                            except Exception as e:  # noqa: BLE001
                                print(f"Failed download Sharewood .torrent for {archive_id}: {e}", file=sys.stderr)
                    if opener:
                        try:
                            subprocess.Popen(  # noqa: S603,S607
                                [opener, url],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            opened += 1
                        except Exception:  # noqa: BLE001
                            print(url)
                    else:
                        print(url)
                    # Don't confirm if we don't have it in qBittorrent yet.
                    continue

                if args.dry_run:
                    print(f"Dry-run: would POST /api/archive/pre-archivage/confirm/{archive_id}")
                else:
                    calewood.confirm_pre_archivage(archive_id)
                    if args.verbose:
                        print(f"confirm {archive_id}: {name}", file=sys.stderr)
                confirmed += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed confirm {archive_id} ({name}): {e}", file=sys.stderr)

        print(
            f"Done. targets={len(targets)} confirmed={confirmed} missing_in_qbit={missing_in_qbit} missing_no_hash={missing_no_hash} opened={opened} skipped={skipped} failed={failed}",
            file=sys.stderr,
        )

        if args.verbose and unknown_lacale_rows:
            def clip(s: str, n: int) -> str:
                s = s or ""
                return s if len(s) <= n else s[: n - 1] + "…"

            headers = ("ID", "SHAREWOOD_HASH", "TORRENT_NAME")
            rows = [(r[0], clip(r[1], 40), clip(r[2], 90)) for r in unknown_lacale_rows]
            widths = [len(h) for h in headers]
            for r in rows:
                for i, c in enumerate(r):
                    widths[i] = max(widths[i], len(c))
            print("\nUnknown lacale_hash (post_archiving):", file=sys.stderr)
            print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))), file=sys.stderr)
            print("  ".join(("-" * widths[i]) for i in range(len(headers))), file=sys.stderr)
            for r in rows:
                print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))), file=sys.stderr)
        return 0 if failed == 0 else 1

    if args.list_archive_prearchivage:
        per_page = 200
        page = 1
        items_all: list[dict] = []
        while True:
            resp = calewood.list_pre_archivage(p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood archive/pre-archivage list failed at page {page}: {resp}")
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

        status_filter = str(args.prearchivage_status or "").strip()
        if status_filter:
            items_all = [it for it in items_all if str(it.get("status") or "").strip() == status_filter]

        items_all.sort(key=lambda it: int(it.get("size_bytes") or 0), reverse=True)

        if args.json:
            for it in items_all:
                print(json.dumps(it, ensure_ascii=False))
            print(f"count={len(items_all)}", file=sys.stderr)
            return 0

        def clip(s: str, n: int) -> str:
            s = s or ""
            return s if len(s) <= n else s[: n - 1] + "…"

        headers = ("ID", "STATUS", "SIZE", "NAME")
        rows: list[tuple[str, str, str, str]] = []
        for it in items_all:
            rows.append(
                (
                    str(it.get("id", "")),
                    clip(str(it.get("status", "") or ""), 18),
                    clip(str(it.get("size_raw", "") or ""), 10),
                    clip(str(it.get("name", "") or ""), 90),
                )
            )
        widths = [len(h) for h in headers]
        for r in rows:
            for i, c in enumerate(r):
                widths[i] = max(widths[i], len(c))
        print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
        print("  ".join(("-" * widths[i]) for i in range(len(headers))))
        for r in rows:
            print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))))
        print(f"\ncount={len(items_all)}", file=sys.stderr)
        return 0

    if args.revert_my_awaiting_fiche_to_selected:
        per_page = 200
        page = 1
        targets: list[dict] = []
        while True:
            resp = calewood.list_pre_archivage(status="my-pre-archiving", p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood archive/pre-archivage list failed at page {page}: {resp}")
            batch = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(batch, list):
                for it in batch:
                    if not isinstance(it, dict):
                        continue
                    if str(it.get("status") or "").strip() != "awaiting_fiche":
                        continue
                    targets.append(it)
            if not has_more:
                break
            page += 1

        abandoned = 0
        took = 0
        skipped = 0
        failed = 0
        for it in targets:
            try:
                archive_id = int(it.get("id"))
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
            name = str(it.get("name", "") or "").strip()
            if args.verbose:
                print(f"Target awaiting_fiche id={archive_id} name={name}", file=sys.stderr)
            try:
                if args.dry_run:
                    print(f"Dry-run: would POST /api/archive/pre-archivage/abandon/{archive_id}")
                    print(f"Dry-run: would POST /api/upload/take/{archive_id}")
                else:
                    calewood.abandon_pre_archivage(archive_id)
                    abandoned += 1
                    calewood.take_upload(archive_id)
                    took += 1
                    print(f"Reverted+Took {archive_id}: {name}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed revert/take {archive_id} ({name}): {e}", file=sys.stderr)

        print(
            f"Done. targets={len(targets)} abandoned={abandoned} took={took} skipped={skipped} failed={failed}",
            file=sys.stderr,
        )
        return 0 if failed == 0 else 1

    if args.list_my_uploading_seedbox_100:
        # Refresh seedbox progress for uploads.
        calewood.seedbox_check_uploads(passphrase=seedbox_passphrase_required())
        if args.verbose:
            print("Triggered /api/upload/seedbox-check", file=sys.stderr)

        exclude_res: list[re.Pattern[str]] = []
        for pat in (args.list_my_uploading_seedbox_100_exclude or []):
            try:
                exclude_res.append(re.compile(str(pat), re.IGNORECASE))
            except re.error as e:
                raise RuntimeError(f"Invalid --list-my-uploading-seedbox-100-exclude: {pat!r}: {e}") from e

        def is_excluded(name: str) -> bool:
            if not exclude_res:
                return False
            return any(r.search(name or "") for r in exclude_res)

        per_page = 200
        page = 1
        items_all: list[dict] = []
        while True:
            resp = calewood.list_uploads(status="my-uploading", p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood upload list failed at page {page}: {resp}")
            batch = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(batch, list):
                for it in batch:
                    if not isinstance(it, dict):
                        continue
                    prog = it.get("seedbox_progress")
                    if prog in (1, 1.0, "1", "1.0", True):
                        name = str(it.get("name", "") or "")
                        if is_excluded(name):
                            continue
                        items_all.append(it)
            if not has_more:
                break
            page += 1

        if args.json:
            for it in items_all:
                print(json.dumps(it, ensure_ascii=False))
            print(f"count={len(items_all)}", file=sys.stderr)
            return 0

        def clip(s: str, n: int) -> str:
            s = s or ""
            return s if len(s) <= n else s[: n - 1] + "…"

        headers = ("ID", "SIZE", "SUBCAT", "NAME")
        rows: list[tuple[str, str, str, str]] = []
        for it in items_all:
            rows.append(
                (
                    str(it.get("id", "")),
                    clip(str(it.get("size_raw", "") or ""), 10),
                    clip(str(it.get("subcategory", "") or ""), 16),
                    clip(str(it.get("name", "") or ""), 90),
                )
            )
        widths = [len(h) for h in headers]
        for r in rows:
            for i, c in enumerate(r):
                widths[i] = max(widths[i], len(c))
        print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
        print("  ".join(("-" * widths[i]) for i in range(len(headers))))
        for r in rows:
            print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))))
        print(f"\ncount={len(items_all)}", file=sys.stderr)
        return 0

    if args.fiche_list is not None:
        status = str(args.fiche_list or "").strip()
        status = status if status else None
        per_page = 200
        page = 1
        items_all: list[dict] = []
        while True:
            resp = calewood.list_upload_pre_archivage(status=status, p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood upload/pre-archivage list failed at page {page}: {resp}")
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

        if args.json:
            for it in items_all:
                print(json.dumps(it, ensure_ascii=False))
            print(f"count={len(items_all)} status={status}", file=sys.stderr)
            return 0

        def clip(s: str, n: int) -> str:
            s = s or ""
            return s if len(s) <= n else s[: n - 1] + "…"

        headers = ("ID", "STATUS", "SIZE", "SUBCAT", "NAME")
        rows: list[tuple[str, str, str, str, str]] = []
        for it in items_all:
            rows.append(
                (
                    str(it.get("id", "")),
                    clip(str(it.get("status", "") or ""), 18),
                    clip(str(it.get("size_raw", "") or ""), 10),
                    clip(str(it.get("subcategory", "") or ""), 16),
                    clip(str(it.get("name", "") or ""), 90),
                )
            )
        widths = [len(h) for h in headers]
        for r in rows:
            for i, c in enumerate(r):
                widths[i] = max(widths[i], len(c))
        print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
        print("  ".join(("-" * widths[i]) for i in range(len(headers))))
        for r in rows:
            print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))))
        print(f"\ncount={len(items_all)} status={status}", file=sys.stderr)
        return 0

    if args.fiche_take is not None:
        tid = int(args.fiche_take)
        if args.dry_run:
            print(f"Dry-run: would POST /api/upload/pre-archivage/take/{tid}")
        else:
            calewood.take_upload_pre_archivage(tid)
            print(f"Took fiche {tid}")
        return 0

    if args.fiche_awaiting_video_subcats:
        per_page = 200
        page = 1
        counts: dict[str, int] = {}
        total = 0
        while True:
            resp = calewood.list_upload_pre_archivage(status="", p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood fiche list failed at page {page}: {resp}")
            batch = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(batch, list):
                for it in batch:
                    if not isinstance(it, dict):
                        continue
                    if str(it.get("status") or "").strip() != "awaiting_fiche":
                        continue
                    if str(it.get("category") or "").strip() != "Vidéos":
                        continue
                    sub = str(it.get("subcategory") or "").strip() or "(empty)"
                    counts[sub] = counts.get(sub, 0) + 1
                    total += 1
            if not has_more:
                break
            page += 1

        for sub, cnt in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower())):
            print(f"{cnt}\t{sub}")
        print(f"total={total} subcats={len(counts)}", file=sys.stderr)
        return 0

    if args.fiche_take_awaiting_category is not None:
        cat = str(args.fiche_take_awaiting_category or "").strip()
        if not cat:
            raise RuntimeError("--fiche-take-awaiting-category requires a non-empty category string.")
        wanted_subcat = str(getattr(args, "fiche_take_subcat", "") or "").strip()
        regexes_raw = [str(r) for r in (args.fiche_take_name_regex or []) if str(r or "").strip()]
        try:
            regexes = [re.compile(r) for r in regexes_raw]
        except re.error as e:
            raise RuntimeError(f"Invalid --fiche-take-name-regex: {e}") from e
        per_page = 200
        page = 1
        matches: list[dict] = []
        while True:
            # Use API-side filtering to reduce pagination and API load.
            resp = calewood.list_upload_pre_archivage(status=None, cat=cat, p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood fiche list failed at page {page}: {resp}")
            batch = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(batch, list):
                for it in batch:
                    if not isinstance(it, dict):
                        continue
                    if str(it.get("status") or "").strip() != "awaiting_fiche":
                        continue
                    if wanted_subcat and str(it.get("subcategory") or "").strip() != wanted_subcat:
                        continue
                    name = str(it.get("name") or "")
                    if regexes and not any(r.search(name) for r in regexes):
                        continue
                    matches.append(it)
                    if args.limit and len(matches) >= int(args.limit):
                        has_more = False
                        break
            if not has_more:
                break
            page += 1

        if matches:
            if args.json:
                for it in matches:
                    print(json.dumps(it, ensure_ascii=False))
                print(f"count={len(matches)} category={cat}", file=sys.stderr)
                return 0
            headers = ("ID", "STATUS", "CAT", "SUBCAT", "NAME", "HASH")
            rows: list[tuple[str, ...]] = []
            for it in matches:
                rows.append(
                    (
                        str(it.get("id", "")),
                        _clip(str(it.get("status", "") or ""), 14),
                        _clip(str(it.get("category", "") or ""), 10),
                        _clip(str(it.get("subcategory", "") or ""), 16),
                        _clip(str(it.get("name", "") or ""), 70),
                        _clip(str(it.get("sharewood_hash", "") or ""), 40),
                    )
                )
            _print_table(headers, rows)
            print("", file=sys.stderr)

        took = 0
        failed = 0
        for it in matches:
            try:
                tid = int(it.get("id"))
            except Exception:  # noqa: BLE001
                failed += 1
                continue
            name = str(it.get("name") or "")
            if args.verbose:
                print(f"Take fiche {tid} category={cat} name={name}", file=sys.stderr)
            if args.dry_run:
                print(f"Dry-run: would POST /api/upload/pre-archivage/take/{tid}")
                continue
            try:
                calewood.take_upload_pre_archivage(tid)
                took += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed take fiche {tid}: {e}", file=sys.stderr)

        if args.dry_run:
            print(f"Dry-run: would take={len(matches)} category={cat}", file=sys.stderr)
            return 0
        print(f"Done. took={took} failed={failed} category={cat}")
        return 0 if failed == 0 else 1

    if args.fiche_complete is not None:
        tid = int(args.fiche_complete)
        url = str(args.fiche_url_lacale or "").strip()
        if not url:
            raise RuntimeError("--fiche-url-lacale is required for --fiche-complete.")
        if args.dry_run:
            print(f"Dry-run: would POST /api/upload/pre-archivage/complete/{tid} url_lacale={url!r}")
        else:
            calewood.complete_upload_pre_archivage(tid, url_lacale=url)
            print(f"Completed fiche {tid}")
        return 0

    if args.fiche_abandon is not None:
        tid = int(args.fiche_abandon)
        if args.dry_run:
            print(f"Dry-run: would POST /api/upload/pre-archivage/abandon/{tid}")
        else:
            calewood.abandon_upload_pre_archivage(tid)
            print(f"Abandoned fiche {tid}")
        return 0

    if args.fiche_blast is not None:
        tid = int(args.fiche_blast)
        reason = str(args.fiche_reason or "").strip()
        if not reason:
            raise RuntimeError("--fiche-reason is required for --fiche-blast.")
        if args.dry_run:
            print(f"Dry-run: would POST /api/upload/pre-archivage/blast/{tid} reason={reason!r}")
        else:
            calewood.blast_upload_pre_archivage(tid, comment=reason)
            print(f"Blasted fiche {tid}")
        return 0

    if args.fiche_scrape is not None:
        tid = int(args.fiche_scrape)
        if args.dry_run:
            print(f"Dry-run: would POST /api/upload/pre-archivage/scrape/{tid}")
        else:
            calewood.scrape_upload_pre_archivage(tid)
            print(f"Scraped fiche {tid}")
        return 0

    if args.fiche_generate_prez is not None:
        tid = int(args.fiche_generate_prez)
        if args.dry_run:
            print(f"Dry-run: would POST /api/upload/pre-archivage/generate-prez/{tid}")
        else:
            calewood.generate_prez_upload_pre_archivage(tid)
            print(f"Generated prez fiche {tid}")
        return 0

    if args.fiche_verify_prez is not None:
        tid = int(args.fiche_verify_prez)
        if args.dry_run:
            print(f"Dry-run: would POST /api/upload/pre-archivage/verify-prez/{tid}")
        else:
            calewood.verify_prez_upload_pre_archivage(tid)
            print(f"Verified prez fiche {tid}")
        return 0

    if args.fiche_post_lacale is not None:
        tid = int(args.fiche_post_lacale)
        if args.dry_run:
            print(f"Dry-run: would POST /api/upload/pre-archivage/post-lacale/{tid} passphrase=***")
        else:
            calewood.post_lacale_upload_pre_archivage(tid, passphrase=seedbox_passphrase_required())
            print(f"Posted fiche to La Cale {tid}")
        return 0

    if args.arbitre_list_q:
        per_page = 200
        page = 1
        all_items: list[dict] = []
        title_res: list[re.Pattern[str]] = []
        for pat in (args.arbitre_list_title_regex or []):
            try:
                title_res.append(re.compile(str(pat), re.IGNORECASE))
            except re.error as e:
                raise RuntimeError(f"Invalid --arbitre-list-title-regex: {pat!r}: {e}") from e

        def title_ok(it: dict) -> bool:
            if not title_res:
                return True
            title = str(it.get("name") or it.get("torrent_name") or "")
            return all(r.search(title or "") for r in title_res)

        def is_ignored(it: dict) -> bool:
            # Default: hide items already ignored / blacklisted / incompatible.
            try:
                ignored_count = int(it.get("ignored_count") or 0)
            except Exception:  # noqa: BLE001
                ignored_count = 0
            ignored_by = it.get("ignored_by")
            if ignored_count > 0:
                return True
            if ignored_by not in (None, "", "null"):
                s = str(ignored_by).strip()
                if s and s not in ("[]", "{}"):
                    return True
            # Blacklist flags are present on some list payloads.
            for k in ("is_blacklisted", "blacklisted", "is_blacklist", "is_blacklisteds"):
                v = it.get(k)
                if v in (1, True, "1", "true", "True"):
                    return True
            # Incompatible flags (naming can vary).
            for k in ("is_incompatible", "incompatible", "incompatible_reason"):
                v = it.get(k)
                if v in (1, True, "1", "true", "True"):
                    return True
                if isinstance(v, str) and v.strip():
                    return True
            return False

        while True:
            resp = calewood.list_arbitre(
                q=str(args.arbitre_list_q),
                status=str(args.arbitre_list_status) if args.arbitre_list_status else None,
                seeders=int(args.arbitre_list_seeders) if args.arbitre_list_seeders is not None else None,
                sort=str(args.arbitre_list_sort) if args.arbitre_list_sort else None,
                order=str(args.arbitre_list_order) if args.arbitre_list_order else None,
                p=page,
                per_page=per_page,
            )
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood arbitre list failed at page {page}: {resp}")
            batch = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(batch, list):
                for it in batch:
                    if isinstance(it, dict) and (not is_ignored(it)) and title_ok(it):
                        all_items.append(it)
            if not has_more:
                break
            page += 1

        if args.arbitre_list_select:
            selected = 0
            owned = 0
            select_failed = 0
            for it in all_items:
                try:
                    arbitre_id = int(it.get("id"))
                except Exception:  # noqa: BLE001
                    continue
                title = str(it.get("name") or it.get("torrent_name") or "")
                if args.dry_run:
                    print(f"Dry-run: would select arbitre {arbitre_id} title={title}")
                    selected += 1
                    continue
                try:
                    calewood.select_arbitre(arbitre_id)
                    if args.verbose:
                        print(f"Selected arbitre {arbitre_id}: {title}", file=sys.stderr)
                    selected += 1
                    if args.arbitre_list_own:
                        if args.dry_run:
                            print(f"Dry-run: would pre-archivage take {arbitre_id} (from arbitre)", file=sys.stderr)
                            owned += 1
                        else:
                            calewood.take_pre_archivage(arbitre_id)
                            if args.verbose:
                                print(f"Pre-archivage took {arbitre_id}", file=sys.stderr)
                            owned += 1
                except Exception as e:  # noqa: BLE001
                    select_failed += 1
                    print(f"Failed select arbitre {arbitre_id}: {e}", file=sys.stderr)

            print(
                f"Done. matched={len(all_items)} selected={selected} owned={owned} failed={select_failed}",
                file=sys.stderr,
            )
            return 0 if select_failed == 0 else 1

        if args.arbitre_list_ignore:
            ignored = 0
            ignore_failed = 0
            for it in all_items:
                try:
                    arbitre_id = int(it.get("id"))
                except Exception:  # noqa: BLE001
                    continue
                title = str(it.get("name") or it.get("torrent_name") or "")
                if args.dry_run:
                    print(f"Dry-run: would ignore arbitre {arbitre_id} comment={args.arbitre_list_ignore_comment!r} title={title}")
                    ignored += 1
                    continue
                try:
                    calewood.ignore_arbitre(arbitre_id, comment=str(args.arbitre_list_ignore_comment))
                    if args.verbose:
                        print(f"Ignored arbitre {arbitre_id}: {title}", file=sys.stderr)
                    ignored += 1
                except Exception as e:  # noqa: BLE001
                    ignore_failed += 1
                    print(f"Failed ignore arbitre {arbitre_id}: {e}", file=sys.stderr)

            print(f"Done. matched={len(all_items)} ignored={ignored} failed={ignore_failed}", file=sys.stderr)
            return 0 if ignore_failed == 0 else 1

        if args.json:
            for it in all_items:
                print(json.dumps(it, ensure_ascii=False))
            print(f"count={len(all_items)}", file=sys.stderr)
            return 0

        def clip(s: str, n: int) -> str:
            s = s or ""
            return s if len(s) <= n else s[: n - 1] + "…"

        headers = ("ID", "STATUS", "SEED", "SIZE", "NAME")
        rows: list[tuple[str, str, str, str, str]] = []
        for it in all_items:
            rows.append(
                (
                    str(it.get("id", "")),
                    clip(str(it.get("status", "") or ""), 16),
                    str(it.get("seeders", "") or ""),
                    clip(str(it.get("size_raw", "") or ""), 10),
                    clip(str(it.get("name", "") or it.get("torrent_name", "") or ""), 80),
                )
            )
        widths = [len(h) for h in headers]
        for r in rows:
            for i, c in enumerate(r):
                widths[i] = max(widths[i], len(c))
        print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
        print("  ".join(("-" * widths[i]) for i in range(len(headers))))
        for r in rows:
            print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))))
        print(f"\ncount={len(all_items)}", file=sys.stderr)
        return 0

    qbit_list = qbit_clients(args.qb_host)
    category_raw = _env("QBIT_CATEGORY", config.QBIT_CATEGORY)
    category = None if category_raw.strip().lower() == "all" else category_raw

    if args.fs_orphans is not None:
        root = os.path.realpath(str(args.fs_orphans))
        ignores = {os.path.realpath(p) for p in (args.fs_ignore or [])}
        maps: list[tuple[str, str]] = []
        for m in args.path_map or []:
            if "=" not in m:
                raise RuntimeError(f"Invalid --path-map (expected FROM=TO): {m}")
            a, b = m.split("=", 1)
            maps.append((a.rstrip("/"), b.rstrip("/")))
        managed_ignores = set(args.managed_ignore_prefix or [])
        if not managed_ignores:
            managed_ignores = {"/incomplete"}

        torrents: list[dict] = []
        for _, qb in qbit_list:
            try:
                torrents.extend(qb.list_torrents(category=None))
            except Exception:  # noqa: BLE001
                continue
        managed_prefixes: set[str] = set()
        for t in torrents:
            for k in ("content_path", "root_path", "save_path", "download_path"):
                v = t.get(k)
                if isinstance(v, str) and v.strip():
                    p = v.strip()
                    if any(p == pref or p.startswith(pref + "/") for pref in managed_ignores):
                        continue
                    for frm, to in maps:
                        if p == frm or p.startswith(frm + "/"):
                            p = to + p[len(frm) :]
                            break
                    managed_prefixes.add(os.path.realpath(p))

        if args.verbose:
            print(f"Managed prefixes: {len(managed_prefixes)}", file=sys.stderr)
            for p in sorted(list(managed_prefixes))[:20]:
                print(f"  {p}", file=sys.stderr)
            if len(managed_prefixes) > 20:
                print("  ...", file=sys.stderr)

        def is_managed(path: str) -> bool:
            for prefix in managed_prefixes:
                if path == prefix or path.startswith(prefix + os.sep):
                    return True
            return False

        def is_ignored(path: str) -> bool:
            if path in ignores:
                return True
            for ign in ignores:
                if path.startswith(ign + os.sep):
                    return True
            return False

        # Recursive scan, but "prune" as soon as we find an unmanaged directory: report it and do not descend.
        orphans: list[str] = []
        stack = [root]
        while stack:
            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    for entry in it:
                        p = os.path.realpath(entry.path)
                        if is_ignored(p):
                            continue
                        # ignore explicit hardcoded dirs if user passed none
                        if not args.fs_ignore and p in {
                            os.path.realpath(os.path.join(root, "1080p")),
                            os.path.realpath(os.path.join(root, "2160p")),
                            os.path.realpath(os.path.join(root, "metube")),
                        }:
                            continue
                        if not is_managed(p):
                            orphans.append(p)
                            # If it's a directory, prune its subtree (we already know it's unmanaged).
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(p)
            except FileNotFoundError:
                continue
            except NotADirectoryError:
                continue

        if args.json:
            for p in sorted(orphans):
                print(json.dumps({"orphan": p}, ensure_ascii=False))
        else:
            print("ORPHAN_PATH")
            print("-----------")
            for p in sorted(orphans):
                print(p)
        print(f"Scanned: {root} | orphans={len(orphans)}", file=sys.stderr)
        return 0

    if args.qbit_missing_lacale_twins:
        lacale_prefix = _env("QBIT_REQUIRED_TRACKER_PREFIX", config.QBIT_REQUIRED_TRACKER_PREFIX)
        exclude_categories = {"cross-seed", "cross seed", "crossseed"}

        torrents: list[dict] = []
        for _, qb in qbit_list:
            try:
                torrents.extend(qb.list_torrents(category=None))
            except Exception:  # noqa: BLE001
                continue
        lacale_names: set[str] = set()
        non_lacale: list[dict] = []

        total = len(torrents)
        for i, torrent in enumerate(torrents, start=1):
            torrent_hash = str(torrent.get("hash", "")).strip()
            name = str(torrent.get("name", "")).strip()
            if not torrent_hash or not name:
                continue
            if i % 50 == 0:
                print(f"Scanning trackers {i}/{total}...", file=sys.stderr)
            trackers = None
            for inst, qb in qbit_list:
                try:
                    trackers = qb.list_trackers(torrent_hash)
                    break
                except Exception:  # noqa: BLE001
                    continue
            if trackers is None:
                continue
            urls = [t.get("url", "") for t in trackers if isinstance(t, dict)]
            is_lacale = any(isinstance(u, str) and u.startswith(lacale_prefix) for u in urls)
            if is_lacale:
                lacale_names.add(name)
            else:
                if str(torrent.get("category", "")).strip().lower() in exclude_categories:
                    continue
                non_lacale.append({"hash": torrent_hash, "name": name, "tracker": torrent.get("tracker")})

        missing = [t for t in non_lacale if t["name"] not in lacale_names]
        if args.limit and args.limit > 0:
            missing = missing[: args.limit]

        if args.verbose:
            print(
                f"Computed missing twins: {len(missing)} (total={total}, lacale_names={len(lacale_names)}, non_lacale={len(non_lacale)})",
                file=sys.stderr,
            )
        if args.json:
            for t in missing:
                print(json.dumps(t, ensure_ascii=False))
            print(f"Total={total} lacale={len(lacale_names)} missing_twins={len(missing)}", file=sys.stderr)
            if args.delete and missing:
                deleted = 0
                for t in missing:
                    h = str(t.get("hash", "")).strip()
                    if not h:
                        continue
                    if args.verbose:
                        print(f"Deleting {h} ({t.get('name','')}) delete_files=true", file=sys.stderr)
                    for inst, qb in qbit_list:
                        try:
                            qb.delete_torrent(h, delete_files=True)
                            if args.verbose:
                                print(f"Deleted from {inst}: {h}", file=sys.stderr)
                        except Exception:  # noqa: BLE001
                            continue
                    deleted += 1
                print(f"Deleted={deleted}", file=sys.stderr)
            return 0

        # Human-readable table
        def clip(s: str, n: int) -> str:
            s = s or ""
            return s if len(s) <= n else s[: n - 1] + "…"

        rows = []
        for t in missing:
            rows.append(
                (
                    clip(str(t.get("hash", "")), 40),
                    clip(str(t.get("tracker", "")), 50),
                    clip(str(t.get("name", "")), 80),
                )
            )

        col1 = max([len("HASH")] + [len(r[0]) for r in rows]) if rows else len("HASH")
        col2 = max([len("TRACKER")] + [len(r[1]) for r in rows]) if rows else len("TRACKER")
        print(f"{'HASH'.ljust(col1)}  {'TRACKER'.ljust(col2)}  NAME")
        print(f"{'-'*col1}  {'-'*col2}  {'-'*4}")
        for h, tr, name in rows:
            print(f"{h.ljust(col1)}  {tr.ljust(col2)}  {name}")
        print(
            f"\nTotal torrents: {total}\nLa-Cale torrents (by tracker): {len(lacale_names)}\nMissing twins: {len(missing)}",
            file=sys.stderr,
        )

        if args.delete and missing:
            deleted = 0
            for t in missing:
                h = str(t.get("hash", "")).strip()
                if not h:
                    continue
                if args.verbose:
                    print(f"Deleting {h} ({t.get('name','')}) delete_files=true", file=sys.stderr)
                for inst, qb in qbit_list:
                    try:
                        qb.delete_torrent(h, delete_files=True)
                        if args.verbose:
                            print(f"Deleted from {inst}: {h}", file=sys.stderr)
                    except Exception:  # noqa: BLE001
                        continue
                deleted += 1
                print(f"Deleted: {h} ({t.get('name','')})", file=sys.stderr)
            print(f"Deleted={deleted}", file=sys.stderr)
        return 0

    if args.qbit_without_lacale_twin:
        lacale_prefix = _env("QBIT_REQUIRED_TRACKER_PREFIX", config.QBIT_REQUIRED_TRACKER_PREFIX)

        # Exclude torrents that are currently in Calewood my-uploading
        uploading_hashes: set[str] = set()
        try:
            per_page = 200
            page = 1
            while True:
                resp = calewood.list_uploads(status="my-uploading", p=page, per_page=per_page)
                if not isinstance(resp, dict) or not resp.get("success"):
                    break
                items = resp.get("data")
                meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
                has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
                if isinstance(items, list):
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        for k in ("sharewood_hash", "lacale_hash"):
                            h = it.get(k)
                            if isinstance(h, str) and h.strip():
                                uploading_hashes.add(h.strip().lower())
                if not has_more:
                    break
                page += 1
        except Exception:  # noqa: BLE001
            uploading_hashes = set()

        torrents: list[dict] = []
        for _, qb in qbit_list:
            try:
                torrents.extend(qb.list_torrents(category=None))
            except Exception:  # noqa: BLE001
                continue
        lacale_names: set[str] = set()
        candidates: list[dict] = []

        total = len(torrents)
        for i, torrent in enumerate(torrents, start=1):
            torrent_hash = str(torrent.get("hash", "")).strip()
            name = str(torrent.get("name", "")).strip()
            if not torrent_hash or not name:
                continue
            if torrent_hash.lower() in uploading_hashes:
                continue
            if i % 50 == 0:
                print(f"Scanning trackers {i}/{total}...", file=sys.stderr)
            trackers = None
            for _, qb in qbit_list:
                try:
                    trackers = qb.list_trackers(torrent_hash)
                    break
                except Exception:  # noqa: BLE001
                    continue
            if trackers is None:
                continue
            urls = [t.get("url", "") for t in trackers if isinstance(t, dict)]
            is_lacale = any(isinstance(u, str) and u.startswith(lacale_prefix) for u in urls)
            if is_lacale:
                lacale_names.add(name)
            else:
                candidates.append(
                    {
                        "hash": torrent_hash,
                        "name": name,
                        "tracker": torrent.get("tracker"),
                        "category": torrent.get("category"),
                    }
                )

        missing = [t for t in candidates if t["name"] not in lacale_names]
        if args.limit and args.limit > 0:
            missing = missing[: args.limit]

        if args.json:
            for t in missing:
                print(json.dumps(t, ensure_ascii=False))
            print(
                f"Total={total} lacale={len(lacale_names)} excluded_my_uploading={len(uploading_hashes)} missing_twins={len(missing)}",
                file=sys.stderr,
            )
            return 0

        def clip(s: str, n: int) -> str:
            s = s or ""
            return s if len(s) <= n else s[: n - 1] + "…"

        rows = []
        for t in missing:
            rows.append(
                (
                    clip(str(t.get("hash", "")), 40),
                    clip(str(t.get("category", "")), 14),
                    clip(str(t.get("tracker", "")), 50),
                    clip(str(t.get("name", "")), 80),
                )
            )
        headers = ("HASH", "CATEGORY", "TRACKER", "NAME")
        widths = [len(h) for h in headers]
        for r in rows:
            for i, c in enumerate(r):
                widths[i] = max(widths[i], len(c))
        print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
        print("  ".join(("-" * widths[i]) for i in range(len(headers))))
        for r in rows:
            print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))))
        print(
            f"\nTotal={total} lacale={len(lacale_names)} excluded_my_uploading={len(uploading_hashes)} missing_twins={len(missing)}",
            file=sys.stderr,
        )
        return 0

    required_status = os.environ.get("CALEWOOD_REQUIRED_STATUS")
    if required_status is None or required_status == "":
        required_status = getattr(config, "CALEWOOD_REQUIRED_STATUS", "uploaded")

    required_tracker_prefix = _env(
        "QBIT_REQUIRED_TRACKER_PREFIX", config.QBIT_REQUIRED_TRACKER_PREFIX
    )
    success_tag = _env("QBIT_SUCCESS_TAG", config.QBIT_SUCCESS_TAG)

    if args.check_my_uploads:
        # Fetch all uploads (paged)
        per_page = 200
        page = 1
        uploads: list[dict] = []
        while True:
            resp = calewood.list_uploads(status="my-uploading", p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood upload list failed at page {page}: {resp}")
            items = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict):
                        uploads.append(it)
            if not has_more:
                break
            page += 1

        hashes = []
        for u in uploads:
            h = u.get("sharewood_hash")
            if isinstance(h, str) and h.strip():
                hashes.append(h.strip().lower())
        qmap: dict[str, dict] = {}
        for _, qb in qbit_list:
            try:
                qmap.update(qb.torrents_by_hashes(hashes))
            except Exception:  # noqa: BLE001
                continue

        rows = []
        for u in uploads:
            sid = u.get("id")
            name = str(u.get("name", "")).strip()
            sharewood_hash = str(u.get("sharewood_hash") or "").strip().lower()
            t = qmap.get(sharewood_hash) if sharewood_hash else None
            if t is None:
                continue
            progress = t.get("progress") if isinstance(t, dict) else None
            is_complete = bool(progress == 1 or progress == 1.0)
            rows.append(
                {
                    "id": sid,
                    "sharewood_hash": sharewood_hash or None,
                    "qb_present": t is not None,
                    "qb_complete": is_complete if t is not None else False,
                    "qb_progress": progress,
                    "name": name,
                }
            )

        if args.json:
            for r in rows:
                print(json.dumps(r, ensure_ascii=False))
            return 0

        # Pretty table
        def clip(s: str, n: int) -> str:
            s = s or ""
            return s if len(s) <= n else s[: n - 1] + "…"

        table = [
            (
                str(r["id"]),
                "Y" if r["qb_present"] else "N",
                "Y" if r["qb_complete"] else "N",
                clip(str(r["qb_progress"]) if r["qb_progress"] is not None else "", 6),
                clip(str(r["sharewood_hash"] or ""), 40),
                clip(str(r["name"]), 70),
            )
            for r in rows
        ]
        headers = ("ID", "IN_QB", "DONE", "PROG", "SHAREWOOD_HASH", "NAME")
        widths = [len(h) for h in headers]
        for row in table:
            for i, col in enumerate(row):
                widths[i] = max(widths[i], len(col))
        print(
            "  ".join(headers[i].ljust(widths[i]) for i in range(len(headers)))
        )
        print(
            "  ".join(("-" * widths[i]) for i in range(len(headers)))
        )
        for row in table:
            print("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))
        done = sum(1 for r in rows if r["qb_complete"])
        print(f"\nPresent in qBittorrent={len(rows)} complete_in_qb={done}", file=sys.stderr)
        return 0

    if args.abandon_stalled_zero:
        # Selected qBittorrent host (mandatory)
        sw_qbit = qbit_from_instance(require_qb_host())
        sw_delete_files = os.environ.get("SW_QBIT_DELETE_FILES", "0").strip() in {"1", "true", "yes"}

        per_page = 200
        page = 1
        uploads: list[dict] = []
        while True:
            resp = calewood.list_uploads(status="my-uploading", p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood upload list failed at page {page}: {resp}")
            items = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict):
                        uploads.append(it)
            if not has_more:
                break
            page += 1

        today = datetime.now().strftime("%Y-%m-%d")
        processed = 0
        for u in uploads:
            upload_id = u.get("id")
            if upload_id is None:
                continue
            try:
                upload_id_int = int(upload_id)
            except Exception:  # noqa: BLE001
                continue

            sharewood_hash = str(u.get("sharewood_hash") or "").strip().lower()
            if not sharewood_hash:
                continue

            t = sw_qbit.get_torrent_by_hash(sharewood_hash)
            if not t:
                continue
            progress = t.get("progress")
            if progress not in (0, 0.0):
                continue

            name = str(u.get("name", "")).strip()
            line = f"Abandon 0 seeder SW|Torr9 {today}"
            try:
                old = calewood.get_torrent_comment(upload_id_int)
                new_comment, changed = append_line_once_prefix(
                    old,
                    prefix="Abandon 0 seeder SW|Torr9",
                    line=line,
                )
                if args.dry_run:
                    if changed:
                        print(f"Dry-run: would update comment for {upload_id_int} ({name}) with: {line}")
                    else:
                        print(f"Dry-run: comment already contains line for {upload_id_int} ({name})")
                    print(f"Dry-run: would POST /api/upload/abandon/{upload_id_int}")
                    print(
                        f"Dry-run: would delete from SW qBittorrent: {sharewood_hash} delete_files={sw_delete_files}"
                    )
                else:
                    if changed:
                        calewood.set_torrent_comment(upload_id_int, new_comment)
                        print(f"Updated comment: {upload_id_int} ({name})")
                    calewood.abandon_upload(upload_id_int)
                    print(f"Abandoned upload: {upload_id_int} ({name})")
                    sw_qbit.delete_torrent(sharewood_hash, delete_files=sw_delete_files)
                    print(
                        f"Deleted from SW qBittorrent: {sharewood_hash} ({t.get('name','')}) delete_files={sw_delete_files}"
                    )
                processed += 1
            except Exception as e:  # noqa: BLE001
                print(f"Failed abandon flow for {upload_id_int} ({name}): {e}", file=sys.stderr)

        print(f"Done. processed={processed}")
        return 0

    if args.calewood_upload_take_low_seeders:
        require_qb_host()
        per_page = 200
        page = 1
        low: list[dict] = []
        while True:
            resp = calewood.list_uploads(status=None, p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood upload list failed at page {page}: {resp}")
            items = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    if str(it.get("status", "")).strip() != "selected":
                        continue
                    try:
                        seeders = int(it.get("seeders") or 0)
                    except Exception:  # noqa: BLE001
                        seeders = 0
                    if seeders <= 1:
                        low.append(it)
            if not has_more:
                break
            page += 1

        cache_path = Path(
            os.environ.get(
                "CALEWOOD_LOW_SEEDERS_IGNORED_CACHE",
                os.path.join(os.getcwd(), ".calewood_low_seeders_ignored.txt"),
            )
        )
        ignored_ids: set[int] = set()
        if cache_path.exists():
            try:
                for line in cache_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    try:
                        ignored_ids.add(int(line.split()[0]))
                    except Exception:  # noqa: BLE001
                        continue
            except Exception:  # noqa: BLE001
                pass

        # Fetch comments for all results
        filtered: list[dict] = []
        # Keep "Abandon 0 seeder SW ..." items (do not filter them out).
        abandon_re = re.compile(r"Abandon 0 seeder\s*(?!SW\b).*", re.IGNORECASE)
        sator_re = re.compile(r"Sat0r le seed", re.IGNORECASE)
        newly_ignored: list[int] = []
        for it in low:
            try:
                tid = int(it.get("id"))
            except Exception:  # noqa: BLE001
                it["__comment"] = ""
                filtered.append(it)
                continue
            if tid in ignored_ids:
                # Skip API calls entirely for cached ignored IDs.
                continue
            try:
                it["__comment"] = calewood.get_torrent_comment(tid)
            except Exception as e:  # noqa: BLE001
                it["__comment"] = f"[comment_error] {e}"
            comment = str(it.get("__comment", "") or "")
            if abandon_re.search(comment):
                newly_ignored.append(tid)
                continue
            filtered.append(it)
        low = filtered
        # Prefer fewer seeders first, then smaller size.
        def _seeders_size_key(it: dict) -> tuple[int, int]:
            try:
                seeders = int(it.get("seeders") or 0)
            except Exception:  # noqa: BLE001
                seeders = 0
            try:
                size_bytes = int(it.get("size_bytes") or 0)
            except Exception:  # noqa: BLE001
                size_bytes = 0
            return (seeders, size_bytes)

        low.sort(key=_seeders_size_key)

        if args.verbose:
            # Show the first items after sorting to confirm ordering.
            preview = []
            for it in low[:20]:
                try:
                    tid = int(it.get("id"))
                except Exception:  # noqa: BLE001
                    tid = -1
                try:
                    seeders = int(it.get("seeders") or 0)
                except Exception:  # noqa: BLE001
                    seeders = 0
                size_bytes = int(it.get("size_bytes") or 0)
                preview.append((seeders, size_bytes, tid, str(it.get("name", "") or "").strip()))
            preview.sort(key=lambda t: (t[0], t[1]))
            print("Budget candidates (seeders asc, then size asc):", file=sys.stderr)
            for seeders, size_bytes, tid, name in preview:
                gib = (size_bytes / (1024**3)) if size_bytes else 0
                print(f"  id={tid} seeders={seeders} size_gib={gib:.2f} {name}", file=sys.stderr)

        if newly_ignored:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with cache_path.open("a", encoding="utf-8") as f:
                    for tid in newly_ignored:
                        f.write(f"{tid}\n")
            except Exception:  # noqa: BLE001
                pass

        if args.json:
            for it in low:
                print(json.dumps(it, ensure_ascii=False))
            print(f"low_seeders={len(low)}", file=sys.stderr)
            return 0

        def clip(s: str, n: int) -> str:
            s = s or ""
            return s if len(s) <= n else s[: n - 1] + "…"

        rows = []
        for it in low:
            rows.append(
                (
                    str(it.get("id", "")),
                    str(it.get("status", "") or ""),
                    str(it.get("seeders", "")),
                    str(it.get("size_raw", "") or ""),
                    str(it.get("subcategory", "") or ""),
                    clip(str(it.get("lacale_hash", "") or ""), 40),
                    clip(str(it.get("sharewood_hash", "") or ""), 40),
                    clip(str(it.get("name", "") or ""), 70),
                    clip(str(it.get("__comment", "") or "").replace("\n", "\\n"), 60),
                )
            )
        headers = ("ID", "STATUS", "SEED", "SIZE", "SUBCAT", "LACALE_HASH", "SHAREWOOD_HASH", "NAME", "COMMENT")
        widths = [len(h) for h in headers]
        for r in rows:
            for i, c in enumerate(r):
                widths[i] = max(widths[i], len(c))
        print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
        print("  ".join(("-" * widths[i]) for i in range(len(headers))))
        for r in rows:
            print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))))
        print(f"\nlow_seeders={len(low)}", file=sys.stderr)
        return 0

    if args.calewood_upload_take_budget_gb is not None:
        require_qb_host()
        budget_bytes = int(args.calewood_upload_take_budget_gb) * 1024 * 1024 * 1024

        # Reuse the same low-seeders fetch+comment+ignore cache logic, but without printing the table.
        per_page = 200
        page = 1
        low: list[dict] = []
        while True:
            resp = calewood.list_uploads(status=None, p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood upload list failed at page {page}: {resp}")
            items = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    # Filters
                    if str(it.get("status", "")).strip() != "selected":
                        continue
                    try:
                        seeders = int(it.get("seeders") or 0)
                    except Exception:  # noqa: BLE001
                        seeders = 0
                    if seeders <= 1:
                        low.append(it)
            if not has_more:
                break
            page += 1

        cache_path = Path(
            os.environ.get(
                "CALEWOOD_LOW_SEEDERS_IGNORED_CACHE",
                os.path.join(os.getcwd(), ".calewood_low_seeders_ignored.txt"),
            )
        )
        ignored_ids: set[int] = set()
        if cache_path.exists():
            try:
                for line in cache_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    try:
                        ignored_ids.add(int(line.split()[0]))
                    except Exception:  # noqa: BLE001
                        continue
            except Exception:  # noqa: BLE001
                pass

        # Keep "Abandon 0 seeder SW ..." items (do not filter them out).
        abandon_re = re.compile(r"Abandon 0 seeder\s*(?!SW\b).*", re.IGNORECASE)
        sator_re = re.compile(r"Sat0r le seed", re.IGNORECASE)
        newly_ignored: list[int] = []
        filtered: list[dict] = []
        for it in low:
            try:
                tid = int(it.get("id"))
            except Exception:  # noqa: BLE001
                filtered.append(it)
                continue
            if tid in ignored_ids:
                continue
            try:
                comment = calewood.get_torrent_comment(tid)
            except Exception:  # noqa: BLE001
                comment = ""
            if abandon_re.search(comment or "") or sator_re.search(comment or ""):
                newly_ignored.append(tid)
                continue
            filtered.append(it)
        low = filtered
        low.sort(key=lambda it: int(it.get("size_bytes") or 0))

        if newly_ignored:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with cache_path.open("a", encoding="utf-8") as f:
                    for tid in newly_ignored:
                        f.write(f"{tid}\n")
            except Exception:  # noqa: BLE001
                pass

        taken = 0
        total_bytes = 0
        for it in low:
            try:
                tid = int(it.get("id"))
            except Exception:  # noqa: BLE001
                continue
            size_bytes = int(it.get("size_bytes") or 0)
            if size_bytes <= 0:
                continue
            # Sorted ascending: if we can't fit this one, none of the next ones will fit either.
            if total_bytes + size_bytes > budget_bytes:
                break
            name = str(it.get("name", "") or "").strip()
            subcat = str(it.get("subcategory", "") or "").strip()
            size_raw = str(it.get("size_raw", "") or "")
            if args.dry_run:
                print(f"Dry-run: would take {tid} subcat={subcat} size={size_raw} name={name}")
            else:
                calewood.take_upload(tid)
                print(f"Took {tid} subcat={subcat} size={size_raw} name={name}")
            total_bytes += size_bytes
            taken += 1

        print(
            f"Done. took={taken} total_gib={total_bytes / (1024**3):.2f} budget_gb={args.calewood_upload_take_budget_gb}",
            file=sys.stderr,
        )
        return 0

    if args.abandon_low_seeders:
        # Build the same low-seeders list as --calewood-upload-take-low-seeders (with ignore cache).
        per_page = 200
        page = 1
        low: list[dict] = []
        while True:
            resp = calewood.list_uploads(status=None, p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood upload list failed at page {page}: {resp}")
            items = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    if str(it.get("category", "")).strip() != "Vidéos":
                        continue
                    subcat = str(it.get("subcategory", "")).strip()
                    if subcat not in {"Films", "Series", "Films Animations"}:
                        continue
                    if str(it.get("status", "")).strip() != "selected":
                        continue
                    try:
                        seeders = int(it.get("seeders") or 0)
                    except Exception:  # noqa: BLE001
                        seeders = 0
                    if seeders <= 1:
                        low.append(it)
            if not has_more:
                break
            page += 1

        cache_path = Path(
            os.environ.get(
                "CALEWOOD_LOW_SEEDERS_IGNORED_CACHE",
                os.path.join(os.getcwd(), ".calewood_low_seeders_ignored.txt"),
            )
        )
        ignored_ids: set[int] = set()
        if cache_path.exists():
            try:
                for line in cache_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    try:
                        ignored_ids.add(int(line.split()[0]))
                    except Exception:  # noqa: BLE001
                        continue
            except Exception:  # noqa: BLE001
                pass

        # Keep "Abandon 0 seeder SW ..." items (do not filter them out).
        abandon_re = re.compile(r"Abandon 0 seeder\s*(?!SW\b).*", re.IGNORECASE)
        newly_ignored: list[int] = []
        targets: list[dict] = []
        for it in low:
            try:
                tid = int(it.get("id"))
            except Exception:  # noqa: BLE001
                continue
            if tid in ignored_ids:
                continue
            try:
                comment = calewood.get_torrent_comment(tid)
            except Exception:  # noqa: BLE001
                comment = ""
            if abandon_re.search(comment or ""):
                newly_ignored.append(tid)
                continue
            it["__comment"] = comment
            targets.append(it)

        if newly_ignored:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with cache_path.open("a", encoding="utf-8") as f:
                    for tid in newly_ignored:
                        f.write(f"{tid}\n")
            except Exception:  # noqa: BLE001
                pass

        targets.sort(key=lambda it: int(it.get("size_bytes") or 0))
        today = datetime.now().strftime("%Y-%m-%d")
        line = f"Sat0r le seed {today}"

        ok = 0
        failed = 0
        for it in targets:
            tid = int(it["id"])
            name = str(it.get("name", "") or "").strip()
            old = str(it.get("__comment", "") or "")
            new_comment, changed = append_line_once_prefix(old, prefix="Sat0r le seed", line=line)
            try:
                if args.dry_run:
                    if changed:
                        print(f"Dry-run: would update comment for {tid} with: {line}")
                    else:
                        print(f"Dry-run: comment already contains line for {tid}")
                    print(f"Dry-run: would abandon upload {tid} ({name})")
                else:
                    if changed:
                        calewood.set_torrent_comment(tid, new_comment)
                    calewood.abandon_upload(tid)
                    print(f"Abandoned {tid}: {name}")
                ok += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed {tid} ({name}): {e}", file=sys.stderr)

        print(f"Done. abandoned={ok} failed={failed}", file=sys.stderr)
        return 0 if failed == 0 else 1

    if args.abandon_my_uploading_non_video:
        per_page = 200
        page = 1
        ids: list[int] = []
        while True:
            resp = calewood.list_uploads(status="my-uploading", p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood upload list failed at page {page}: {resp}")
            items = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    try:
                        ids.append(int(it.get("id")))
                    except Exception:  # noqa: BLE001
                        continue
            if not has_more:
                break
            page += 1

        abandoned = 0
        kept = 0
        for upload_id in ids:
            info = calewood.get_upload(upload_id)
            data = None
            if isinstance(info, dict) and info.get("success") and isinstance(info.get("data"), dict):
                data = info["data"]
            elif isinstance(info, dict):
                # Sometimes APIs return the object directly in data[]
                data = info

            if not isinstance(data, dict):
                print(f"Skip {upload_id}: unexpected get_upload response", file=sys.stderr)
                continue

            category = str(data.get("category", "")).strip()
            subcat = str(data.get("subcategory", "")).strip()
            name = str(data.get("name", "")).strip()

            is_video_ok = category == "Vidéos" and subcat in {"Films", "Series", "Films Animations"}
            if is_video_ok:
                kept += 1
                if args.verbose:
                    print(f"Keep {upload_id}: {category}/{subcat} {name}", file=sys.stderr)
                continue

            if args.dry_run:
                print(f"Dry-run: would abandon {upload_id}: {category}/{subcat} {name}")
            else:
                calewood.abandon_upload(upload_id)
                print(f"Abandoned {upload_id}: {category}/{subcat} {name}")
            abandoned += 1

        print(f"Done. abandoned={abandoned} kept={kept}", file=sys.stderr)
        return 0

    if args.calewood_upload_take_ready is not None:
        target = int(args.calewood_upload_take_ready)
        if target <= 0:
            print("X must be > 0", file=sys.stderr)
            return 2

        per_page = 200
        page = 1
        selected: list[dict] = []
        while True:
            resp = calewood.list_uploads(status="selected", p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood upload list failed at page {page}: {resp}")
            batch = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(batch, list):
                for it in batch:
                    if isinstance(it, dict):
                        selected.append(it)
            if not has_more:
                break
            page += 1

        # Largest first
        selected.sort(key=lambda it: int(it.get("size_bytes") or 0), reverse=True)

        taken = 0
        skipped = 0
        failed = 0
        for it in selected:
            if taken >= target:
                break
            try:
                tid = int(it.get("id"))
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
            name = str(it.get("name", "") or "").strip()
            sharewood_hash = str(it.get("sharewood_hash", "") or "").strip().lower()
            if not sharewood_hash:
                skipped += 1
                continue

            t = None
            for _, qb in qbit_list:
                try:
                    t = qb.get_torrent_by_hash(sharewood_hash)
                    if t is not None:
                        break
                except Exception:  # noqa: BLE001
                    continue
            if not t or t.get("progress") not in (1, 1.0):
                skipped += 1
                continue

            try:
                if args.dry_run:
                    print(f"Dry-run: would take {tid} ({name}) sharewood_hash={sharewood_hash}")
                else:
                    calewood.take_upload(tid)
                    print(f"Took {tid}: {name}")
                taken += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed take {tid} ({name}): {e}", file=sys.stderr)

        print(f"Done. took={taken} skipped={skipped} failed={failed}", file=sys.stderr)
        return 0 if failed == 0 else 1

    if args.calewood_upload_take_owned_complete:
        # Needs qBittorrent to check progress==1.0 by sharewood_hash.
        qbit_list = qbit_clients(require_qb_host())
        qb = qbit_list[0][1]

        per_page = 200
        page = 1
        selected: list[dict] = []
        while True:
            resp = calewood.list_uploads(status="selected", p=page, per_page=per_page)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood upload list failed at page {page}: {resp}")
            batch = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if isinstance(batch, list):
                for it in batch:
                    if isinstance(it, dict):
                        selected.append(it)
            if not has_more:
                break
            page += 1

        taken = 0
        skipped = 0
        failed = 0
        for it in selected:
            try:
                tid = int(it.get("id"))
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
            name = str(it.get("name", "") or "").strip()
            sharewood_hash = str(it.get("sharewood_hash", "") or "").strip().lower()
            if not sharewood_hash:
                skipped += 1
                continue

            try:
                t = qb.get_torrent_by_hash(sharewood_hash)
            except Exception:  # noqa: BLE001
                t = None
            if not t or t.get("progress") not in (1, 1.0):
                skipped += 1
                continue

            if args.verbose:
                print(f"Owned complete: {tid} ({name}) sharewood_hash={sharewood_hash}", file=sys.stderr)
            try:
                if args.dry_run:
                    print(f"Dry-run: would take {tid} ({name}) sharewood_hash={sharewood_hash}")
                else:
                    calewood.take_upload(tid)
                    print(f"Took {tid}: {name}")
                taken += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"Failed take {tid} ({name}): {e}", file=sys.stderr)

        print(f"Done. took={taken} skipped={skipped} failed={failed}", file=sys.stderr)
        return 0 if failed == 0 else 1

    if args.calewood_upload_take_zero_seeders:
        per_page = 200
        page = 1
        taken = 0
        skipped = 0
        failed = 0
        scanned = 0
        matched = 0
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
                    try:
                        tid = int(it.get("id"))
                    except Exception:  # noqa: BLE001
                        skipped += 1
                        continue
                    name = str(it.get("name", "") or "").strip()
                    try:
                        seeders = int(it.get("seeders") or 0)
                    except Exception:  # noqa: BLE001
                        seeders = 0
                    if seeders != 0:
                        skipped += 1
                        continue
                    matched += 1
                    if args.verbose:
                        print(f"Match {tid} seeders=0: {name}", file=sys.stderr)
                    try:
                        if args.dry_run:
                            print(f"Dry-run: would take {tid} ({name})")
                        else:
                            calewood.take_upload(tid)
                            print(f"Took {tid}: {name}")
                        taken += 1
                    except Exception as e:  # noqa: BLE001
                        failed += 1
                        print(f"Failed take {tid} ({name}): {e}", file=sys.stderr)

            if not has_more:
                break
            page += 1

        print(
            f"Done. scanned={scanned} matched={matched} took={taken} skipped={skipped} failed={failed}",
            file=sys.stderr,
        )
        return 0 if failed == 0 else 1

    if args.shutup_take_my_storage:
        per_page = 200
        page = 1
        taken = 0
        skipped = 0
        failed = 0
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
                    try:
                        tid = int(it.get("id"))
                    except Exception:  # noqa: BLE001
                        skipped += 1
                        continue
                    name = str(it.get("name", "") or "").strip()
                    if args.verbose:
                        print(f"Take {tid}: {name}", file=sys.stderr)
                    try:
                        if args.dry_run:
                            print(f"Dry-run: would take {tid} ({name})")
                        else:
                            calewood.take_upload(tid)
                            print(f"Took {tid}: {name}")
                        taken += 1
                    except Exception as e:  # noqa: BLE001
                        failed += 1
                        print(f"Failed take {tid} ({name}): {e}", file=sys.stderr)

            if not has_more:
                break
            page += 1

        print(f"Done. scanned={scanned} took={taken} skipped={skipped} failed={failed}", file=sys.stderr)
        return 0 if failed == 0 else 1

    if args.arbitre_q:
        # Fixed list params (user request)
        per_page = 200
        page = 1
        took = 0
        checked = 0
        skipped = 0
        failed = 0
        rows: list[tuple[str, str, str, str, str, str]] = []
        exclude_res: list[re.Pattern[str]] = []
        for pat in (args.arbitre_exclude or []):
            try:
                exclude_res.append(re.compile(str(pat), re.IGNORECASE))
            except re.error as e:
                raise RuntimeError(f"Invalid --arbitre-exclude regex: {pat!r}: {e}") from e

        def clip(s: str, n: int) -> str:
            s = s or ""
            return s if len(s) <= n else s[: n - 1] + "…"

        def is_excluded(torrent_name: str) -> bool:
            if not exclude_res:
                return False
            for r in exclude_res:
                if r.search(torrent_name or ""):
                    return True
            return False

        def is_ignored(it: dict) -> bool:
            # Default: hide items already ignored / blacklisted / incompatible.
            try:
                ignored_count = int(it.get("ignored_count") or 0)
            except Exception:  # noqa: BLE001
                ignored_count = 0
            ignored_by = it.get("ignored_by")
            if ignored_count > 0:
                return True
            if ignored_by not in (None, "", "null"):
                s = str(ignored_by).strip()
                if s and s not in ("[]", "{}"):
                    return True
            for k in ("is_blacklisted", "blacklisted", "is_blacklist", "is_blacklisteds"):
                v = it.get(k)
                if v in (1, True, "1", "true", "True"):
                    return True
            for k in ("is_incompatible", "incompatible", "incompatible_reason"):
                v = it.get(k)
                if v in (1, True, "1", "true", "True"):
                    return True
                if isinstance(v, str) and v.strip():
                    return True
            return False

        resp = calewood.list_arbitre(
            q=str(args.arbitre_q),
            seeders=1,
            sort="size_bytes",
            order="desc",
            p=page,
            per_page=per_page,
        )
        if not isinstance(resp, dict) or not resp.get("success"):
            raise RuntimeError(f"Calewood arbitre list failed: {resp}")
        items = resp.get("data")

        filtered_items: list[dict] = []
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                try:
                    _ = int(it.get("id"))
                except Exception:  # noqa: BLE001
                    skipped += 1
                    continue
                torrent_name_list = str(it.get("torrent_name") or it.get("name") or "")
                if is_ignored(it):
                    continue
                if is_excluded(torrent_name_list):
                    if not args.json:
                        rows.append(
                            (
                                str(it.get("id", "")),
                                clip(str(it.get("torrent_id") or it.get("torrent") or ""), 12),
                                clip(torrent_name_list, 70),
                                clip(str(it.get("seeders") or ""), 6),
                                "",
                                "excluded",
                            )
                        )
                    continue
                filtered_items.append(it)

        # Dry-run: do not check any endpoints; just show filtered list.
        if args.dry_run or not args.arbitre_take:
            if args.json:
                for it in filtered_items:
                    print(json.dumps(it, ensure_ascii=False))
                return 0

            for it in filtered_items:
                rows.append(
                    (
                        str(it.get("id", "")),
                        clip(str(it.get("torrent_id") or it.get("torrent") or ""), 12),
                        clip(str(it.get("torrent_name") or it.get("name") or ""), 70),
                        clip(str(it.get("seeders") or ""), 6),
                        "",
                        "new",
                    )
                )

            headers = ("ID", "TORRENT_ID", "TORRENT_NAME", "SEED", "CHECKS", "ACTION")
            widths = [len(h) for h in headers]
            for r in rows:
                for i, c in enumerate(r):
                    widths[i] = max(widths[i], len(c))
            print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
            print("  ".join(("-" * widths[i]) for i in range(len(headers))))
            for r in rows:
                print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))))
            return 0

        # Not dry-run + --arbitre-take: run checks for each filtered item.
        for it in filtered_items:
            try:
                arbitre_id = int(it.get("id"))
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
            torrent_name_list = str(it.get("torrent_name") or it.get("name") or "")
            torrent_id_list = str(it.get("torrent_id") or it.get("torrent") or "")
            seeders_list = str(it.get("seeders") or "")

            lacale_ok = "?"
            c411_ok = "?"
            get_ok = "?"
            try:
                lacale = calewood.check_arbitre_lacale(arbitre_id)
                lacale_ok = "ok"
            except Exception as e:  # noqa: BLE001
                failed += 1
                lacale_ok = "fail"
                if args.verbose:
                    print(f"check-lacale fail id={arbitre_id}: {e}", file=sys.stderr)
                lacale = None
            try:
                c411 = calewood.check_arbitre_c411(arbitre_id)
                c411_ok = "ok"
            except Exception as e:  # noqa: BLE001
                failed += 1
                c411_ok = "fail"
                if args.verbose:
                    print(f"check-c411 fail id={arbitre_id}: {e}", file=sys.stderr)
                c411 = None
            try:
                get = calewood.get_arbitre(arbitre_id)
                get_ok = "ok"
            except Exception as e:  # noqa: BLE001
                failed += 1
                get_ok = "fail"
                if args.verbose:
                    print(f"get fail id={arbitre_id}: {e}", file=sys.stderr)
                get = None

            checked += 1

            if args.json:
                print(json.dumps({"id": arbitre_id, "check_lacale": lacale, "check_c411": c411, "get": get}, ensure_ascii=False))
                continue

            checks = f"lacale={lacale_ok} c411={c411_ok} get={get_ok}"
            action = "checked"
            if args.arbitre_own:
                # Required: reserve/claim the arbitre item first.
                try:
                    if args.verbose:
                        print(f"Select arbitre {arbitre_id}", file=sys.stderr)
                    if not args.dry_run:
                        calewood.select_arbitre(arbitre_id)
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    action = "select-fail"
                    print(f"Failed arbitre select {arbitre_id}: {e}", file=sys.stderr)
                    rows.append(
                        (
                            str(arbitre_id),
                            clip(torrent_id_list, 12),
                            clip(torrent_name_list, 70),
                            clip(seeders_list, 6),
                            clip(checks, 24),
                            action,
                        )
                    )
                    continue

                # After select, take the matching upload by the same internal id.
                # (API error shows upload/take expects the internal upload id and must be in status=selected.)
                try:
                    info = calewood.get_upload(arbitre_id)
                    upload_status = None
                    if isinstance(info, dict) and isinstance(info.get("data"), dict):
                        upload_status = str(info["data"].get("status") or "").strip()
                    if upload_status != "selected":
                        action = f"own-skip({upload_status or 'unknown'})"
                    else:
                        if args.dry_run:
                            action = "dry-took-upload"
                        else:
                            calewood.take_upload(arbitre_id)
                            action = "took-upload"
                            took += 1
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    action = "take-fail"
                    print(f"Failed upload take {arbitre_id} (after select): {e}", file=sys.stderr)

            rows.append(
                (
                    str(arbitre_id),
                    clip(torrent_id_list, 12),
                    clip(torrent_name_list, 70),
                    clip(seeders_list, 6),
                    clip(checks, 24),
                    action,
                )
            )

        headers = ("ID", "TORRENT_ID", "TORRENT_NAME", "SEED", "CHECKS", "ACTION")
        widths = [len(h) for h in headers]
        for r in rows:
            for i, c in enumerate(r):
                widths[i] = max(widths[i], len(c))
        print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
        print("  ".join(("-" * widths[i]) for i in range(len(headers))))
        for r in rows:
            print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))))

        print(f"Done. checked={checked} took={took} skipped={skipped} failed={failed}", file=sys.stderr)
        return 0 if failed == 0 else 1

    if args.process_calewood_list:
        ok = 0
        skipped = 0
        failed = 0
        per_page = 200
        max_pages = 500

        for page in range(1, max_pages + 1):
            resp = calewood.list_archives(p=page, per_page=per_page, v1_only=0)
            if not isinstance(resp, dict) or not resp.get("success"):
                raise RuntimeError(f"Calewood list failed at page {page}: {resp}")
            items = resp.get("data")
            meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
            has_more = bool(meta.get("has_more")) if isinstance(meta, dict) else False
            if not isinstance(items, list) or not items:
                break

            for item in items:
                if not isinstance(item, dict):
                    continue
                item_status = str(item.get("status", "")).strip().lower()
                if required_status and item_status != str(required_status).strip().lower():
                    continue

                archive_id = str(item.get("id", "")).strip()
                lacale_hash = str(item.get("lacale_hash", "")).strip().lower()
                name = str(item.get("name", "")).strip()
                if not archive_id or not lacale_hash:
                    skipped += 1
                    continue

                qb_found = None
                t = None
                for inst, qb in qbit_list:
                    try:
                        t = qb.get_torrent_by_hash(lacale_hash)
                    except Exception:  # noqa: BLE001
                        t = None
                    if t:
                        qb_found = (inst, qb)
                        break
                if not t or qb_found is None:
                    skipped += 1
                    continue

                # Ensure tracker requirement is satisfied for safety.
                try:
                    trackers = qb_found[1].list_trackers(lacale_hash)
                except Exception:  # noqa: BLE001
                    skipped += 1
                    continue
                tracker_urls = [tr.get("url", "") for tr in trackers if isinstance(tr, dict)]
                if not any(
                    isinstance(url, str) and url.startswith(required_tracker_prefix) for url in tracker_urls
                ):
                    skipped += 1
                    continue

                try:
                    if args.dry_run:
                        ok += 1
                        print(f"Dry-run: would POST take: {archive_id} ({name})")
                        print(f"Dry-run: would POST complete: {archive_id} ({name})")
                        print(f"Dry-run: would tag '{success_tag}': {lacale_hash} ({t.get('name','')})")
                    else:
                        calewood.take_archive(archive_id)
                        print(f"Took: {archive_id} ({name})")
                        calewood.complete_archive(archive_id)
                        ok += 1
                        print(f"Completed: {archive_id} ({name})")
                        qb_found[1].add_tag(lacale_hash, success_tag)
                        print(
                            f"Tagged '{success_tag}': {lacale_hash} ({t.get('name','')}) on {qb_found[0]}"
                        )
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    print(f"Failed: {archive_id} ({name}): {e}", file=sys.stderr)

            if not has_more:
                break

        print(f"Done. ok={ok} skipped={skipped} failed={failed}")
        return 0 if failed == 0 else 1

    parser.print_help(sys.stderr)
    return 2
