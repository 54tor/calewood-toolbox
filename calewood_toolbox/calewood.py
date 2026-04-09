from __future__ import annotations

import json
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass


@dataclass(frozen=True)
class CalewoodClient:
    base_url: str
    token: str

    def __post_init__(self) -> None:
        # Allow configuring CALEWOOD_BASE_URL either as:
        # - https://host
        # - https://host/api
        # Internally we keep the non-/api base and all callers use paths starting with "api/".
        base = (self.base_url or "").rstrip("/")
        if base.endswith("/api"):
            base = base[: -len("/api")]
        object.__setattr__(self, "base_url", base)

    def _auth_value(self) -> str:
        t = (self.token or "").strip()
        if t.lower().startswith("bearer "):
            return t
        return f"Bearer {t}"

    def _headers(self) -> dict[str, str]:
        # Some front proxies (e.g. Cloudflare) may block requests without a User-Agent.
        return {
            "Authorization": self._auth_value(),
            "User-Agent": "curl/8.0 (calewood-toolbox)",
            "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
        }

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: object | None = None,
        timeout: int = 30,
    ) -> object:
        url = urllib.parse.urljoin(self.base_url + "/", path.lstrip("/"))
        if params:
            url = url + "?" + urllib.parse.urlencode(params)
        headers = dict(self._headers())
        data: bytes | None = None
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, headers=headers, data=data, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                payload = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                body = ""
            body = body.strip()
            snippet = (body[:500] + "…") if len(body) > 500 else body
            raise RuntimeError(f"Calewood HTTP {e.code} {e.reason}: {snippet}") from e
        try:
            return json.loads(payload)
        except Exception:  # noqa: BLE001
            return payload.strip()

    def _request_bytes(self, path: str, *, params: dict[str, str] | None = None, timeout: int = 30) -> bytes:
        url = urllib.parse.urljoin(self.base_url + "/", path.lstrip("/"))
        if params:
            url = url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return resp.read()
        except urllib.error.HTTPError as e:
            raw = b""
            try:
                raw = e.read()
            except Exception:  # noqa: BLE001
                raw = b""
            snippet = raw[:200].decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Calewood HTTP {e.code} {e.reason}: {snippet}") from e

    def _request_bytes_external(self, url: str, *, timeout: int = 60) -> bytes:
        """GET an absolute URL and return response bytes (used for La-Cale torrent downloads)."""
        req = urllib.request.Request(str(url), headers={}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return resp.read()
        except urllib.error.HTTPError as e:
            raw = b""
            try:
                raw = e.read()
            except Exception:  # noqa: BLE001
                raw = b""
            snippet = raw[:200].decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"HTTP {e.code} {e.reason}: {snippet}") from e

    def complete_archive(self, archive_id: str) -> None:
        url = urllib.parse.urljoin(self.base_url + "/", f"api/archive/complete/{archive_id}")
        req = urllib.request.Request(
            url,
            data=b"",
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                resp.read()
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                body = ""
            body = body.strip()
            snippet = (body[:500] + "…") if len(body) > 500 else body
            raise RuntimeError(f"Calewood HTTP {e.code} {e.reason}: {snippet}") from e

    def take_archive(self, archive_id: str) -> None:
        url = urllib.parse.urljoin(self.base_url + "/", f"api/archive/take/{archive_id}")
        req = urllib.request.Request(
            url,
            data=b"",
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                resp.read()
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                body = ""
            body = body.strip()
            snippet = (body[:500] + "…") if len(body) > 500 else body
            raise RuntimeError(f"Calewood HTTP {e.code} {e.reason}: {snippet}") from e

    def revert_archive_done(self, archive_id: int) -> object:
        """POST /api/archive/revert-done/{id}."""
        return self._request_json("POST", f"api/archive/revert-done/{int(archive_id)}")

    def seedbox_check_archives(self, *, passphrase: str) -> object:
        """POST /api/archive/seedbox-check. Body JSON: {"passphrase":"..."}."""
        pp = str(passphrase or "").strip()
        if not pp:
            raise RuntimeError("passphrase is required for /api/archive/seedbox-check")
        return self._request_json("POST", "api/archive/seedbox-check", json_body={"passphrase": pp})

    def get_archive(self, archive_id: int) -> object:
        url = urllib.parse.urljoin(self.base_url + "/", f"api/archive/get/{int(archive_id)}")
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                payload = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                body = ""
            body = body.strip()
            snippet = (body[:500] + "…") if len(body) > 500 else body
            raise RuntimeError(f"Calewood HTTP {e.code} {e.reason}: {snippet}") from e
        try:
            return json.loads(payload)
        except Exception:  # noqa: BLE001
            return payload.strip()

    def list_uploads(
        self,
        *,
        status: str | None = None,
        q: str | None = None,
        cat: str | None = None,
        subcat: str | None = None,
        sort: str | None = None,
        order: str | None = None,
        p: int = 1,
        per_page: int = 50,
    ) -> object:
        url = urllib.parse.urljoin(self.base_url + "/", "api/upload/list")
        params: dict[str, str] = {"p": str(p), "per_page": str(per_page)}
        if status is not None and str(status).strip() != "":
            params["status"] = str(status).strip()
        if q is not None and str(q).strip() != "":
            params["q"] = str(q).strip()
        if cat is not None and str(cat).strip() != "":
            params["cat"] = str(cat).strip()
        if subcat is not None and str(subcat).strip() != "":
            params["subcat"] = str(subcat).strip()
        if sort is not None and str(sort).strip() != "":
            params["sort"] = str(sort).strip()
        if order is not None and str(order).strip() != "":
            params["order"] = str(order).strip()
        url = url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                payload = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                body = ""
            body = body.strip()
            snippet = (body[:500] + "…") if len(body) > 500 else body
            raise RuntimeError(f"Calewood HTTP {e.code} {e.reason}: {snippet}") from e
        try:
            return json.loads(payload)
        except Exception:  # noqa: BLE001
            return payload.strip()

    def get_upload(self, upload_id: int) -> object:
        url = urllib.parse.urljoin(self.base_url + "/", f"api/upload/get/{int(upload_id)}")
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                payload = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                body = ""
            body = body.strip()
            snippet = (body[:500] + "…") if len(body) > 500 else body
            raise RuntimeError(f"Calewood HTTP {e.code} {e.reason}: {snippet}") from e
        try:
            return json.loads(payload)
        except Exception:  # noqa: BLE001
            return payload.strip()

    def get_torrent_comment(self, torrent_id: int) -> str:
        url = urllib.parse.urljoin(self.base_url + "/", f"api/torrent/comment/{int(torrent_id)}")
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                payload = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                body = ""
            body = body.strip()
            snippet = (body[:500] + "…") if len(body) > 500 else body
            raise RuntimeError(f"Calewood HTTP {e.code} {e.reason}: {snippet}") from e
        # Expect either raw string or JSON {success,data:{comment}}; handle both.
        try:
            data = json.loads(payload)
            if isinstance(data, dict) and data.get("success") and isinstance(data.get("data"), dict):
                return str(data["data"].get("comment", ""))
        except Exception:  # noqa: BLE001
            pass
        return payload.strip()

    def set_torrent_comment(self, torrent_id: int, comment: str) -> None:
        url = urllib.parse.urljoin(self.base_url + "/", f"api/torrent/comment/{int(torrent_id)}")
        body = json.dumps({"comment": comment}, ensure_ascii=False).encode("utf-8")
        headers = dict(self._headers())
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                resp.read()
        except urllib.error.HTTPError as e:
            raw = ""
            try:
                raw = e.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                raw = ""
            raw = raw.strip()
            snippet = (raw[:500] + "…") if len(raw) > 500 else raw
            raise RuntimeError(f"Calewood HTTP {e.code} {e.reason}: {snippet}") from e

    def abandon_upload(self, upload_id: int) -> None:
        url = urllib.parse.urljoin(self.base_url + "/", f"api/upload/abandon/{int(upload_id)}")
        req = urllib.request.Request(url, data=b"", headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                resp.read()
        except urllib.error.HTTPError as e:
            raw = ""
            try:
                raw = e.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                raw = ""
            raw = raw.strip()
            snippet = (raw[:500] + "…") if len(raw) > 500 else raw
            raise RuntimeError(f"Calewood HTTP {e.code} {e.reason}: {snippet}") from e

    def list_torrents(self, *, q: str | None = None, p: int = 1, per_page: int = 50) -> object:
        """GET /api/torrent/list (paged). Supports q=... search."""
        params: dict[str, str] = {"per_page": str(int(per_page)), "p": str(int(p))}
        if q is not None and str(q).strip() != "":
            params["q"] = str(q).strip()
        qs = "?" + urllib.parse.urlencode(params)
        return self._request_json("GET", f"api/torrent/list{qs}")

    def take_upload(self, upload_id: int) -> None:
        url = urllib.parse.urljoin(self.base_url + "/", f"api/upload/take/{int(upload_id)}")
        req = urllib.request.Request(url, data=b"", headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                resp.read()
        except urllib.error.HTTPError as e:
            raw = ""
            try:
                raw = e.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                raw = ""
            raw = raw.strip()
            snippet = (raw[:500] + "…") if len(raw) > 500 else raw
            raise RuntimeError(f"Calewood HTTP {e.code} {e.reason}: {snippet}") from e

    # ---- Upload stubs / helpers from raw_api_notes ----

    def complete_upload(self, upload_id: int, *, url_lacale: str) -> object:
        """POST /api/upload/complete/{id} (uploading -> uploaded)."""
        return self._request_json(
            "POST",
            f"api/upload/complete/{int(upload_id)}",
            json_body={"url_lacale": url_lacale},
        )

    def scrape_upload(self, upload_id: int) -> object:
        """POST /api/upload/scrape/{id}."""
        return self._request_json("POST", f"api/upload/scrape/{int(upload_id)}")

    def get_upload_content(self, upload_id: int, *, content_type: str) -> object:
        """GET /api/upload/content/{id}?type=prez|nfo."""
        if content_type not in {"prez", "nfo"}:
            raise ValueError("content_type must be 'prez' or 'nfo'")
        return self._request_json(
            "GET",
            f"api/upload/content/{int(upload_id)}",
            params={"type": content_type},
        )

    def download_upload_torrent_file(self, upload_id: int) -> bytes:
        """GET /api/upload/torrent-file/{id} (binary .torrent)."""
        return self._request_bytes(f"api/upload/torrent-file/{int(upload_id)}")

    def search_media(
        self,
        upload_id: int,
        *,
        query: str | None = None,
        tmdb_type: str | None = None,
        engine: str | None = None,
    ) -> object:
        """POST /api/upload/search-media/{id}."""
        body: dict[str, object] = {}
        if query is not None:
            body["query"] = query
        if tmdb_type is not None:
            body["tmdb_type"] = tmdb_type
        if engine is not None:
            body["engine"] = engine
        return self._request_json("POST", f"api/upload/search-media/{int(upload_id)}", json_body=body)

    def generate_prez(
        self,
        upload_id: int,
        *,
        tmdb_id: int | None = None,
        tmdb_type: str | None = None,
        gbooks_id: str | None = None,
        force: bool | None = None,
        correction: str | None = None,
        engine: str | None = None,
    ) -> object:
        """POST /api/upload/generate-prez/{id}."""
        body: dict[str, object] = {}
        if tmdb_id is not None:
            body["tmdb_id"] = int(tmdb_id)
        if tmdb_type is not None:
            body["tmdb_type"] = tmdb_type
        if gbooks_id is not None:
            body["gbooks_id"] = gbooks_id
        if force is not None:
            body["force"] = bool(force)
        if correction is not None:
            body["correction"] = correction
        if engine is not None:
            body["engine"] = engine
        return self._request_json("POST", f"api/upload/generate-prez/{int(upload_id)}", json_body=body)

    def verify_prez(self, upload_id: int, *, force: bool = False) -> object:
        """POST /api/upload/verify-prez/{id}."""
        return self._request_json(
            "POST",
            f"api/upload/verify-prez/{int(upload_id)}",
            json_body={"force": bool(force)},
        )

    def post_lacale(self, upload_id: int, *, passphrase: str, return_mode: str | None = None) -> object | bytes:
        """
        POST /api/upload/post-lacale/{id}
        return_mode: torrent|url|none (see raw_api_notes). May return JSON or binary .torrent.
        """
        body: dict[str, object] = {"passphrase": passphrase}
        if return_mode is not None:
            body["return"] = return_mode
        url = urllib.parse.urljoin(self.base_url + "/", f"api/upload/post-lacale/{int(upload_id)}")
        headers = dict(self._headers())
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
                ctype = resp.headers.get("Content-Type", "")
                payload = resp.read()
                if "application/json" in ctype:
                    try:
                        return json.loads(payload.decode("utf-8", errors="replace"))
                    except Exception:  # noqa: BLE001
                        return payload.decode("utf-8", errors="replace").strip()
                return payload
        except urllib.error.HTTPError as e:
            raw = ""
            try:
                raw = e.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                raw = ""
            raw = raw.strip()
            snippet = (raw[:500] + "…") if len(raw) > 500 else raw
            raise RuntimeError(f"Calewood HTTP {e.code} {e.reason}: {snippet}") from e

    def blast_upload(self, upload_id: int, *, comment: str | None = None) -> object:
        """POST /api/upload/blast/{id}."""
        body = {"comment": comment} if comment is not None else {}
        return self._request_json("POST", f"api/upload/blast/{int(upload_id)}", json_body=body)

    def seedbox_check_uploads(self, *, passphrase: str) -> object:
        """POST /api/upload/seedbox-check. Body JSON: {"passphrase":"..."}."""
        pp = str(passphrase or "").strip()
        if not pp:
            raise RuntimeError("passphrase is required for /api/upload/seedbox-check")
        return self._request_json("POST", "api/upload/seedbox-check", json_body={"passphrase": pp})

    # Endpoint mentioned in raw_api_notes but not used by current CLI:
    # - /api/upload/torrent-file/{id} (implemented as download_upload_torrent_file)
    # - /api/upload/content/{id} (implemented as get_upload_content)
    # - /api/upload/search-media/{id} (implemented as search_media)
    # - /api/upload/generate-prez/{id} (implemented as generate_prez)
    # - /api/upload/verify-prez/{id} (implemented as verify_prez)
    # - /api/upload/post-lacale/{id} (implemented as post_lacale)

    def list_archives(
        self,
        *,
        status: str | None = None,
        q: str | None = None,
        cat: str | None = None,
        subcat: str | None = None,
        seeders: int | None = None,
        min_size: str | None = None,
        max_size: str | None = None,
        arbitre: int | None = None,
        uploader: int | None = None,
        sort: str | None = None,
        order: str | None = None,
        p: int = 1,
        per_page: int = 50,
        v1_only: int | None = None,
    ) -> object:
        url = urllib.parse.urljoin(self.base_url + "/", "api/archive/list")
        params: dict[str, str] = {"per_page": str(per_page), "p": str(p)}
        if status is not None and str(status).strip() != "":
            params["status"] = str(status).strip()
        if q is not None and str(q).strip() != "":
            params["q"] = str(q).strip()
        if cat is not None and str(cat).strip() != "":
            params["cat"] = str(cat).strip()
        if subcat is not None and str(subcat).strip() != "":
            params["subcat"] = str(subcat).strip()
        if seeders is not None:
            params["seeders"] = str(int(seeders))
        if min_size is not None and str(min_size).strip() != "":
            params["min_size"] = str(min_size).strip()
        if max_size is not None and str(max_size).strip() != "":
            params["max_size"] = str(max_size).strip()
        if arbitre is not None:
            params["arbitre"] = str(int(arbitre))
        if uploader is not None:
            params["uploader"] = str(int(uploader))
        if sort is not None and str(sort).strip() != "":
            params["sort"] = str(sort).strip()
        if order is not None and str(order).strip() != "":
            params["order"] = str(order).strip()
        if v1_only is not None:
            params["v1_only"] = str(int(v1_only))
        url = url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                payload = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                body = ""
            body = body.strip()
            snippet = (body[:500] + "…") if len(body) > 500 else body
            raise RuntimeError(f"Calewood HTTP {e.code} {e.reason}: {snippet}") from e
        try:
            return json.loads(payload)
        except Exception:  # noqa: BLE001
            return payload.strip()

    # ---- Arbitre API (arbitrage) ----

    def list_arbitre(
        self,
        *,
        q: str | None = None,
        status: str | None = None,
        seeders: int | None = None,
        sort: str | None = None,
        order: str | None = None,
        p: int = 1,
        per_page: int = 50,
    ) -> object:
        """GET /api/arbitre/list (paged)."""
        params: dict[str, str] = {"per_page": str(int(per_page)), "p": str(int(p))}
        if q is not None and str(q).strip() != "":
            params["q"] = str(q).strip()
        if status is not None and str(status).strip() != "":
            params["status"] = str(status).strip()
        if seeders is not None:
            params["seeders"] = str(int(seeders))
        if sort is not None and str(sort).strip() != "":
            params["sort"] = str(sort).strip()
        if order is not None and str(order).strip() != "":
            params["order"] = str(order).strip()
        qs = "?" + urllib.parse.urlencode(params)
        return self._request_json("GET", f"api/arbitre/list{qs}")

    def check_arbitre_lacale(self, arbitre_id: int) -> object:
        """GET /api/arbitre/check-lacale/{id}."""
        return self._request_json("GET", f"api/arbitre/check-lacale/{int(arbitre_id)}")

    def check_arbitre_c411(self, arbitre_id: int) -> object:
        """GET /api/arbitre/check-c411/{id}."""
        return self._request_json("GET", f"api/arbitre/check-c411/{int(arbitre_id)}")

    def get_arbitre(self, arbitre_id: int) -> object:
        """GET /api/arbitre/get/{id}."""
        return self._request_json("GET", f"api/arbitre/get/{int(arbitre_id)}")

    def select_arbitre(self, arbitre_id: int) -> object:
        """POST /api/arbitre/select/{id}."""
        return self._request_json("POST", f"api/arbitre/select/{int(arbitre_id)}", json_body={})

    def bulk_select_arbitre(self, ids: list[int]) -> object:
        """POST /api/arbitre/bulk-select."""
        return self._request_json("POST", "api/arbitre/bulk-select", json_body={"ids": [int(i) for i in ids]})

    def ignore_arbitre(self, arbitre_id: int, *, comment: str | None = None) -> object:
        """POST /api/arbitre/ignore/{id}."""
        body = {"comment": comment} if comment is not None else {}
        return self._request_json("POST", f"api/arbitre/ignore/{int(arbitre_id)}", json_body=body)

    def bulk_ignore_arbitre(self, ids: list[int]) -> object:
        """POST /api/arbitre/bulk-ignore."""
        return self._request_json("POST", "api/arbitre/bulk-ignore", json_body={"ids": [int(i) for i in ids]})

    def stage_arbitre(self, arbitre_id: int) -> object:
        """POST /api/arbitre/stage/{id}."""
        return self._request_json("POST", f"api/arbitre/stage/{int(arbitre_id)}", json_body={})

    def unstage_arbitre(self, arbitre_id: int) -> object:
        """POST /api/arbitre/unstage/{id}."""
        return self._request_json("POST", f"api/arbitre/unstage/{int(arbitre_id)}", json_body={})

    def bulk_stage_arbitre(self, ids: list[int]) -> object:
        """POST /api/arbitre/bulk-stage."""
        return self._request_json("POST", "api/arbitre/bulk-stage", json_body={"ids": [int(i) for i in ids]})

    def list_arbitre_staging(self) -> object:
        """GET /api/arbitre/staging."""
        return self._request_json("GET", "api/arbitre/staging")

    # ---- Pre-archivage ----

    # Archiviste flow
    def list_pre_archivage(
        self,
        *,
        status: str | None = None,
        q: str | None = None,
        cat: str | None = None,
        subcat: str | None = None,
        seeders: int | None = None,
        min_size: str | None = None,
        max_size: str | None = None,
        p: int = 1,
        per_page: int = 50,
    ) -> object:
        """GET /api/archive/pre-archivage/list (paged)."""
        params: dict[str, str] = {"per_page": str(int(per_page)), "p": str(int(p))}
        if status is not None and str(status).strip() != "":
            params["status"] = str(status).strip()
        if q is not None and str(q).strip() != "":
            params["q"] = str(q).strip()
        if cat is not None and str(cat).strip() != "":
            params["cat"] = str(cat).strip()
        if subcat is not None and str(subcat).strip() != "":
            params["subcat"] = str(subcat).strip()
        if seeders is not None:
            params["seeders"] = str(int(seeders))
        if min_size is not None and str(min_size).strip() != "":
            params["min_size"] = str(min_size).strip()
        if max_size is not None and str(max_size).strip() != "":
            params["max_size"] = str(max_size).strip()
        qs = "?" + urllib.parse.urlencode(params)
        return self._request_json("GET", f"api/archive/pre-archivage/list{qs}")

    def take_pre_archivage(self, archive_id: int) -> object:
        """POST /api/archive/pre-archivage/take/{id} (selected -> pre_archiving)."""
        return self._request_json("POST", f"api/archive/pre-archivage/take/{int(archive_id)}", json_body={})

    def dl_done_pre_archivage(self, archive_id: int) -> object:
        """POST /api/archive/pre-archivage/dl-done/{id} (pre_archiving -> awaiting_fiche)."""
        return self._request_json("POST", f"api/archive/pre-archivage/dl-done/{int(archive_id)}", json_body={})

    def confirm_pre_archivage(self, archive_id: int) -> object:
        """POST /api/archive/pre-archivage/confirm/{id} (post_archiving -> done)."""
        return self._request_json("POST", f"api/archive/pre-archivage/confirm/{int(archive_id)}", json_body={})

    def abandon_pre_archivage(self, archive_id: int) -> object:
        """POST /api/archive/pre-archivage/abandon/{id} (pre_archiving/awaiting_fiche -> selected)."""
        return self._request_json("POST", f"api/archive/pre-archivage/abandon/{int(archive_id)}", json_body={})

    def blast_pre_archivage(self, archive_id: int, *, comment: str | None = None) -> object:
        """POST /api/archive/pre-archivage/blast/{id} (pre_archiving/awaiting_fiche -> new)."""
        body = {"comment": comment} if comment is not None else {}
        return self._request_json("POST", f"api/archive/pre-archivage/blast/{int(archive_id)}", json_body=body)

    def download_pre_archivage_torrent_file(self, archive_id: int) -> bytes:
        """GET /api/archive/pre-archivage/torrent-file/{id} (binary .torrent)."""
        url = urllib.parse.urljoin(self.base_url + "/", f"api/archive/pre-archivage/torrent-file/{int(archive_id)}")
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                return resp.read()
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                body = ""
            body = body.strip()
            snippet = (body[:500] + "…") if len(body) > 500 else body
            raise RuntimeError(f"Calewood HTTP {e.code} {e.reason}: {snippet}") from e

    # Uploader flow
    def list_upload_pre_archivage(
        self,
        *,
        status: str | None = None,
        q: str | None = None,
        cat: str | None = None,
        p: int = 1,
        per_page: int = 50,
    ) -> object:
        """GET /api/upload/pre-archivage/list (paged)."""
        params: dict[str, str] = {"per_page": str(int(per_page)), "p": str(int(p))}
        if status is not None and str(status).strip() != "":
            params["status"] = str(status).strip()
        if q is not None and str(q).strip() != "":
            params["q"] = str(q).strip()
        if cat is not None and str(cat).strip() != "":
            params["cat"] = str(cat).strip()
        qs = "?" + urllib.parse.urlencode(params)
        return self._request_json("GET", f"api/upload/pre-archivage/list{qs}")

    def take_upload_pre_archivage(self, upload_id: int) -> object:
        """POST /api/upload/pre-archivage/take/{id}."""
        return self._request_json("POST", f"api/upload/pre-archivage/take/{int(upload_id)}", json_body={})

    def complete_upload_pre_archivage(self, upload_id: int, *, url_lacale: str) -> object:
        """POST /api/upload/pre-archivage/complete/{id} (awaiting_fiche -> post_archiving)."""
        return self._request_json(
            "POST",
            f"api/upload/pre-archivage/complete/{int(upload_id)}",
            json_body={"url_lacale": str(url_lacale)},
        )

    def abandon_upload_pre_archivage(self, upload_id: int) -> object:
        """POST /api/upload/pre-archivage/abandon/{id}."""
        return self._request_json("POST", f"api/upload/pre-archivage/abandon/{int(upload_id)}", json_body={})

    def blast_upload_pre_archivage(self, upload_id: int, *, comment: str | None = None) -> object:
        """POST /api/upload/pre-archivage/blast/{id} (awaiting_fiche -> new)."""
        # Doc says `reason` is mandatory. Keep `comment` arg for convenience but send as `reason`.
        reason = str(comment or "").strip()
        body = {"reason": reason} if reason else {}
        return self._request_json("POST", f"api/upload/pre-archivage/blast/{int(upload_id)}", json_body=body)

    def scrape_upload_pre_archivage(self, upload_id: int) -> object:
        """POST /api/upload/pre-archivage/scrape/{id}."""
        return self._request_json("POST", f"api/upload/pre-archivage/scrape/{int(upload_id)}", json_body={})

    def search_media_upload_pre_archivage(self, upload_id: int) -> object:
        """POST /api/upload/pre-archivage/search-media/{id}."""
        return self._request_json("POST", f"api/upload/pre-archivage/search-media/{int(upload_id)}", json_body={})

    def generate_prez_upload_pre_archivage(self, upload_id: int) -> object:
        """POST /api/upload/pre-archivage/generate-prez/{id}."""
        return self._request_json("POST", f"api/upload/pre-archivage/generate-prez/{int(upload_id)}", json_body={})

    def verify_prez_upload_pre_archivage(self, upload_id: int) -> object:
        """POST /api/upload/pre-archivage/verify-prez/{id}."""
        return self._request_json("POST", f"api/upload/pre-archivage/verify-prez/{int(upload_id)}", json_body={})

    def post_lacale_upload_pre_archivage(self, upload_id: int, *, passphrase: str) -> object:
        """POST /api/upload/pre-archivage/post-lacale/{id}."""
        return self._request_json(
            "POST",
            f"api/upload/pre-archivage/post-lacale/{int(upload_id)}",
            json_body={"passphrase": str(passphrase)},
        )

    # ---- Resurrection ----

    def list_resurrection(self, *, p: int = 1, per_page: int = 50) -> object:
        """GET /api/resurrection/list (paged)."""
        qs = "?" + urllib.parse.urlencode({"per_page": str(int(per_page)), "p": str(int(p))})
        return self._request_json("GET", f"api/resurrection/list{qs}")

    def promote_resurrection(self, resurrection_id: int) -> object:
        """POST /api/resurrection/promote/{id}."""
        return self._request_json("POST", f"api/resurrection/promote/{int(resurrection_id)}", json_body={})

    def blast_resurrection(self, resurrection_id: int, *, comment: str | None = None) -> object:
        """POST /api/resurrection/blast/{id}."""
        body = {"comment": comment} if comment is not None else {}
        return self._request_json("POST", f"api/resurrection/blast/{int(resurrection_id)}", json_body=body)

    def find_archive_id(self, *, q: str, per_page: int = 50) -> int | None:
        data = self.list_archives(q=q, p=1, per_page=per_page, v1_only=0)
        if not isinstance(data, dict) or not data.get("success"):
            return None
        items = data.get("data")
        if not isinstance(items, list) or not items:
            return None
        first = items[0]
        if not isinstance(first, dict):
            return None
        try:
            return int(first["id"])
        except Exception:  # noqa: BLE001
            return None

    def build_lacale_hash_map(
        self,
        *,
        archivist_id: int | None = None,
        required_status: str | None = "uploaded",
        per_page: int = 200,
        max_pages: int = 200,
    ) -> dict[str, int]:
        """
        Returns mapping: lacale_hash (lowercase) -> archive id (int).
        Filters client-side to avoid depending on server filter parameter names.
        """
        mapping: dict[str, int] = {}
        status_wanted = (required_status or "").strip().lower() or None

        for page in range(1, max_pages + 1):
            data = self.list_archives(p=page, per_page=per_page, v1_only=0)
            if not isinstance(data, dict) or not data.get("success"):
                break
            items = data.get("data")
            if not isinstance(items, list) or not items:
                break

            for item in items:
                if not isinstance(item, dict):
                    continue

                if status_wanted is not None:
                    if str(item.get("status", "")).strip().lower() != status_wanted:
                        continue

                if archivist_id is not None:
                    item_archivist = item.get("archivist_id", item.get("archivistId"))
                    try:
                        if int(item_archivist) != int(archivist_id):
                            continue
                    except Exception:  # noqa: BLE001
                        continue

                lacale_hash = str(item.get("lacale_hash", "")).strip().lower()
                if not lacale_hash:
                    continue
                try:
                    archive_id = int(item["id"])
                except Exception:  # noqa: BLE001
                    continue
                mapping[lacale_hash] = archive_id

            meta = data.get("meta")
            has_more = False
            if isinstance(meta, dict):
                has_more = bool(meta.get("has_more"))
            if not has_more:
                break

        return mapping

    def iter_all_archives(self, *, per_page: int = 200, max_pages: int = 500) -> list[dict]:
        """Fetches all pages of /api/archive/list and returns the concatenated items."""
        all_items: list[dict] = []
        for page in range(1, max_pages + 1):
            data = self.list_archives(p=page, per_page=per_page, v1_only=0)
            if not isinstance(data, dict) or not data.get("success"):
                break
            items = data.get("data")
            if not isinstance(items, list) or not items:
                break
            for item in items:
                if isinstance(item, dict):
                    all_items.append(item)
            meta = data.get("meta")
            has_more = False
            if isinstance(meta, dict):
                has_more = bool(meta.get("has_more"))
            if not has_more:
                break
        return all_items
