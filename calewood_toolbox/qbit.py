from __future__ import annotations

from dataclasses import dataclass, field
import io

import qbittorrentapi


@dataclass
class QbitClient:
    base_url: str
    username: str
    password: str
    _client_cached: qbittorrentapi.Client | None = field(default=None, init=False, repr=False)

    def _client(self) -> qbittorrentapi.Client:
        if self._client_cached is not None:
            return self._client_cached
        client = qbittorrentapi.Client(
            host=self.base_url,
            username=self.username,
            password=self.password,
            REQUESTS_ARGS={"timeout": 60},
        )
        client.auth_log_in()
        self._client_cached = client
        return client

    def list_torrents(self, category: str | None) -> list[dict]:
        client = self._client()
        if category is None:
            torrents = client.torrents_info()
        else:
            torrents = client.torrents_info(category=category)
        return [dict(t) for t in torrents]

    def list_trackers(self, torrent_hash: str) -> list[dict]:
        client = self._client()
        trackers = client.torrents_trackers(torrent_hash=torrent_hash)
        return [dict(t) for t in trackers]

    def add_tag(self, torrent_hash: str, tag: str) -> None:
        client = self._client()
        # qBittorrent uses "tags" (sometimes called labels in UI).
        client.torrents_add_tags(tags=tag, torrent_hashes=torrent_hash)

    def set_category(self, torrent_hash: str, category: str) -> None:
        client = self._client()
        h = str(torrent_hash or "").strip()
        if not h:
            return
        client.torrents_set_category(torrent_hashes=h, category=category)

    def set_location(self, torrent_hash: str, location: str) -> None:
        client = self._client()
        h = str(torrent_hash or "").strip()
        loc = str(location or "").strip()
        if not h or not loc:
            return
        # This moves data on disk.
        client.torrents_set_location(torrent_hashes=h, location=loc)

    def set_save_path(self, torrent_hash: str, save_path: str) -> None:
        client = self._client()
        h = str(torrent_hash or "").strip()
        sp = str(save_path or "").strip()
        if not h or not sp:
            return
        # This changes the save path without moving data (qBittorrent API semantics).
        client.torrents_set_save_path(torrent_hashes=h, save_path=sp)

    def export_torrent_file(self, torrent_hash: str) -> bytes:
        client = self._client()
        h = str(torrent_hash or "").strip()
        if not h:
            return b""
        return bytes(client.torrents_export(torrent_hash=h))

    def delete_torrent(self, torrent_hash: str, *, delete_files: bool = True) -> None:
        client = self._client()
        h = str(torrent_hash or "").strip()
        if not h:
            return
        client.torrents_delete(torrent_hashes=h, delete_files=bool(delete_files))

    def add_torrent_file(
        self,
        torrent_bytes: bytes,
        *,
        category: str | None = None,
        start: bool = True,
        save_path: str | None = None,
        skip_checking: bool = False,
    ) -> None:
        client = self._client()
        bio = io.BytesIO(torrent_bytes or b"")
        paused = not bool(start)
        client.torrents_add(
            torrent_files=bio,
            category=category,
            paused=paused,
            save_path=save_path,
            skip_checking=bool(skip_checking),
        )

    def remove_trackers(self, torrent_hash: str, urls: str | list[str]) -> None:
        client = self._client()
        h = str(torrent_hash or "").strip()
        if not h:
            return
        client.torrents_remove_trackers(torrent_hash=h, urls=urls)

    def add_trackers(self, torrent_hash: str, urls: str | list[str]) -> None:
        client = self._client()
        h = str(torrent_hash or "").strip()
        if not h:
            return
        client.torrents_add_trackers(torrent_hash=h, urls=urls)

    def pause_torrents(self, hashes: list[str]) -> None:
        client = self._client()
        joined = "|".join([h for h in hashes if str(h).strip()])
        if not joined:
            return
        client.torrents_pause(torrent_hashes=joined)

    def resume_torrents(self, hashes: list[str]) -> None:
        client = self._client()
        joined = "|".join([h for h in hashes if str(h).strip()])
        if not joined:
            return
        client.torrents_resume(torrent_hashes=joined)

    def bottom_prio(self, hashes: list[str]) -> None:
        client = self._client()
        joined = "|".join([h for h in hashes if str(h).strip()])
        if not joined:
            return
        # Move torrents to the bottom of the queue (queueing must be enabled in qBittorrent settings).
        client.torrents_bottom_priority(torrent_hashes=joined)

    def torrents_by_hashes(self, hashes: list[str]) -> dict[str, dict]:
        client = self._client()
        # qbittorrent-api accepts a "|" separated list for torrent_hashes.
        joined = "|".join([h for h in hashes if h])
        if not joined:
            return {}
        torrents = client.torrents_info(torrent_hashes=joined)
        result: dict[str, dict] = {}
        for t in torrents:
            d = dict(t)
            h = str(d.get("hash", "")).lower()
            if h:
                result[h] = d
        return result

    def get_torrent_by_hash(self, torrent_hash: str) -> dict | None:
        client = self._client()
        h = str(torrent_hash or "").strip()
        if not h:
            return None
        torrents = client.torrents_info(torrent_hashes=h)
        for t in torrents:
            d = dict(t)
            if str(d.get("hash", "")).lower() == h.lower():
                return d
        return None
