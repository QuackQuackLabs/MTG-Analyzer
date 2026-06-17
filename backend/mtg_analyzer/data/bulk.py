"""Scryfall bulk-data downloader.

Polls ``/bulk-data``, downloads the Oracle Cards and Rulings files, and re-downloads
only when Scryfall's ``updated_at`` changes (tracked in a local manifest). Streams to
disk so memory stays bounded regardless of file size. httpx transparently decodes the
gzip transfer-encoding, so the on-disk files are plain JSON.

See the ``scryfall-api`` skill for the bulk-data catalog and refresh guidance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import httpx

from mtg_analyzer import config


@dataclass(frozen=True)
class BulkFile:
    bulk_type: str
    path: Path
    updated_at: str


class BulkDataManager:
    def __init__(self, scryfall_dir: Path | None = None) -> None:
        self.dir = scryfall_dir or config.SCRYFALL_DIR
        self.manifest_path = self.dir / "manifest.json"

    # --- manifest -----------------------------------------------------------
    def _load_manifest(self) -> dict[str, dict[str, str]]:
        if self.manifest_path.exists():
            return json.loads(self.manifest_path.read_text())
        return {}

    def _save_manifest(self, manifest: dict[str, dict[str, str]]) -> None:
        self.manifest_path.write_text(json.dumps(manifest, indent=2))

    def local_file(self, bulk_type: str) -> BulkFile | None:
        """Return the locally cached file for a bulk type, or None if absent."""
        entry = self._load_manifest().get(bulk_type)
        if not entry:
            return None
        path = self.dir / entry["file"]
        if not path.exists():
            return None
        return BulkFile(bulk_type=bulk_type, path=path, updated_at=entry["updated_at"])

    # --- network ------------------------------------------------------------
    def fetch_catalog(self) -> dict[str, dict]:
        """GET /bulk-data → {bulk_type: entry} keyed on the entry's ``type``."""
        resp = httpx.get(
            f"{config.SCRYFALL_API_BASE}/bulk-data",
            headers=config.DEFAULT_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        return {entry["type"]: entry for entry in resp.json()["data"]}

    def download(self, bulk_type: str, *, force: bool = False) -> BulkFile:
        """Download ``bulk_type`` if its ``updated_at`` changed (or ``force``)."""
        config.ensure_dirs()
        catalog = self.fetch_catalog()
        if bulk_type not in catalog:
            raise ValueError(f"Unknown bulk type {bulk_type!r}; have {sorted(catalog)}")
        entry = catalog[bulk_type]
        updated_at = entry["updated_at"]

        cached = self.local_file(bulk_type)
        if cached and cached.updated_at == updated_at and not force:
            return cached  # up to date

        dest = self.dir / f"{bulk_type}.json"
        self._stream_to_file(entry["download_uri"], dest)

        manifest = self._load_manifest()
        manifest[bulk_type] = {"file": dest.name, "updated_at": updated_at}
        self._save_manifest(manifest)
        return BulkFile(bulk_type=bulk_type, path=dest, updated_at=updated_at)

    def _stream_to_file(self, url: str, dest: Path) -> None:
        tmp = dest.with_suffix(dest.suffix + ".part")
        with (
            httpx.stream("GET", url, headers=config.DEFAULT_HEADERS, timeout=None) as resp,
            tmp.open("wb") as fh,
        ):
            resp.raise_for_status()
            for chunk in resp.iter_bytes():  # httpx decodes gzip → plain JSON bytes
                fh.write(chunk)
        tmp.replace(dest)  # atomic swap so a partial download never looks complete
