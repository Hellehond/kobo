"""Keeps the SQLite catalogue in step with the files in the library folder."""
from __future__ import annotations

import logging
import subprocess
import threading
import time
import uuid as uuidlib
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .config import Config
from .db import Database
from . import epubfix
from .epubmeta import read_metadata
from .util import parse_loose_date

log = logging.getLogger(__name__)

# Bump when the way books are processed changes, so existing books are
# processed again on the next scan.
PROCESSING_VERSION = 2
COLLECTION_SEPARATOR = " / "


def detect_format(path: Path) -> Optional[str]:
    name = path.name.lower()
    if name.startswith("."):
        return None
    if name.endswith(".kepub.epub") or name.endswith(".kepub"):
        return "KEPUB"
    if name.endswith(".epub"):
        return "EPUB"
    return None


class Library:
    def __init__(self, cfg: Config, db: Database):
        self.cfg = cfg
        self.db = db
        self._lock = threading.Lock()
        self._last_scan = 0.0

    @property
    def proc_key(self) -> str:
        c = self.cfg
        flags = [
            f"v{PROCESSING_VERSION}",
            f"split={int(c.split_authors)}",
            f"css={int(c.fix_styles)}",
            f"front={int(c.move_front_matter)}",
            f"kepub={int(bool(c.kepubify))}",
        ]
        return ";".join(flags)

    # ----------------------------------------------------------------- scanning

    def scan_if_due(self) -> None:
        if time.monotonic() - self._last_scan >= self.cfg.scan_interval:
            self.scan()

    def scan(self) -> Dict[str, int]:
        """Import new files, refresh changed ones and archive the ones that disappeared."""
        if not self._lock.acquire(blocking=False):
            # Another thread is scanning; it will pick everything up.
            return {"added": 0, "updated": 0, "restored": 0, "missing": 0}
        try:
            return self._scan()
        finally:
            self._last_scan = time.monotonic()
            self._lock.release()

    def _scan(self) -> Dict[str, int]:
        stats = {"added": 0, "updated": 0, "restored": 0, "missing": 0}
        seen = set()
        root = self.cfg.library_dir
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            fmt = detect_format(path)
            if fmt is None:
                continue
            rel = path.relative_to(root).as_posix()
            seen.add(rel)
            try:
                st = path.stat()
            except OSError:
                continue
            existing = self.db.book_by_path(rel)
            if existing is None:
                self._import(path, rel, fmt, st.st_size, st.st_mtime, None)
                stats["added"] += 1
                continue
            changed = (existing["size"] != st.st_size or abs(existing["mtime"] - st.st_mtime) > 1e-6
                       or existing.get("proc_key") != self.proc_key)
            if changed:
                self._import(path, rel, fmt, st.st_size, st.st_mtime, existing)
                stats["updated"] += 1
            if existing["archived"] and existing["archived_reason"] == "missing":
                self.db.restore_book(existing["id"])
                stats["restored"] += 1
                log.info("Restored %s (file is back)", rel)

        for book in self.db.all_books(include_archived=False):
            if book["path"] not in seen:
                self.db.archive_book(book["id"], "missing")
                stats["missing"] += 1
                log.info("Archived %s (file removed from library)", book["path"])
        if any(stats.values()):
            log.info("Library scan: %s", ", ".join(f"{k}={v}" for k, v in stats.items()))
        self.reconcile_collections()
        return stats

    def _import(self, path: Path, rel: str, fmt: str, size: int, mtime: float,
                existing: Optional[Dict[str, Any]]) -> int:
        meta = read_metadata(path, split=self.cfg.split_authors)
        book_uuid = existing["uuid"] if existing else str(uuidlib.uuid4())
        cover_name = None
        if meta.cover:
            data, ext = meta.cover
            cover_name = f"{book_uuid}{ext}"
            (self.cfg.covers_dir / cover_name).write_bytes(data)

        # A cleaned-up copy, if the book needs one, then KEPUB conversion of
        # whichever version is served.
        processed = self.cfg.processed_dir / f"{book_uuid}.epub"
        report = epubfix.process(path, processed, fix_styles=self.cfg.fix_styles,
                                 move_front_matter=self.cfg.move_front_matter)
        source = processed if report.changed else path
        log.info("%s: %s", rel, report.summary())

        fields = dict(
            path=rel, format=fmt, size=size, mtime=mtime,
            title=meta.title, authors=meta.authors or ["Onbekend"],
            language=meta.language, publisher=meta.publisher, description=meta.description,
            pubdate=parse_loose_date(meta.pubdate), isbn=meta.isbn,
            series=meta.series, series_index=meta.series_index, cover=cover_name,
            processed_path=processed.name if report.changed else None,
            kepub_path=None, proc_key=self.proc_key,
        )
        if fmt == "EPUB" and self.cfg.kepubify:
            fields["kepub_path"] = self._convert_kepub(source, book_uuid)
        if existing:
            self.db.update_book(existing["id"], **fields)
            log.info("Updated %s (%s)", meta.title, rel)
            return existing["id"]
        book_id = self.db.insert_book(uuid=book_uuid, **fields)
        log.info("Added %s by %s (%s)", meta.title, ", ".join(fields["authors"]), rel)
        return book_id

    def _convert_kepub(self, path: Path, book_uuid: str) -> Optional[str]:
        out = self.cfg.kepub_dir / f"{book_uuid}.kepub.epub"
        try:
            if out.exists():
                out.unlink()
            proc = subprocess.run(
                [self.cfg.kepubify, "-o", str(out), str(path)],
                capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("kepubify failed for %s: %s", path.name, exc)
            return None
        if proc.returncode != 0 or not out.exists():
            log.warning("kepubify failed for %s: %s", path.name, (proc.stderr or proc.stdout).strip())
            return None
        return out.name

    # ------------------------------------------------------------------- files

    def file_for_book(self, book: Dict[str, Any]) -> Tuple[Path, str]:
        """Return (path, kobo format) of the file to hand to the device."""
        if book.get("kepub_path"):
            kepub = self.cfg.kepub_dir / book["kepub_path"]
            if kepub.exists():
                return kepub, "KEPUB"
        if book.get("processed_path"):
            processed = self.cfg.processed_dir / book["processed_path"]
            if processed.exists():
                return processed, book["format"]
        return self.cfg.library_dir / book["path"], book["format"]

    # ------------------------------------------------------------- collections

    @staticmethod
    def collection_name(rel_path: str) -> Optional[str]:
        """"Thrillers/Noors/arr.epub" -> "Thrillers / Noors"; books in the root have none."""
        parts = rel_path.split("/")[:-1]
        return COLLECTION_SEPARATOR.join(parts) if parts else None

    def reconcile_collections(self) -> None:
        """Make the folder collections match the folders the (active) books are in."""
        desired: Dict[str, list] = {}
        if self.cfg.folder_collections:
            for book in self.db.all_books(include_archived=False):
                name = self.collection_name(book["path"])
                if name:
                    desired.setdefault(name, []).append(book["uuid"])
        for items in desired.values():
            items.sort()
        existing = {t["name"]: t for t in self.db.all_tags(source="folder")}
        for name, items in desired.items():
            tag = existing.get(name)
            if tag is None:
                self.db.insert_tag(str(uuidlib.uuid4()), name, items)
                log.info("Collection '%s' created (%d book(s))", name, len(items))
            elif tag["deleted"]:
                # The folder is back: offer it to the devices as a new collection again.
                self.db.update_tag(tag["id"], items=items, deleted=0, created=time.time())
            elif tag["items"] != items:
                self.db.update_tag(tag["id"], items=items)
        for name, tag in existing.items():
            if name not in desired and not tag["deleted"]:
                self.db.update_tag(tag["id"], items=[], deleted=1)
                log.info("Collection '%s' removed (folder is empty or gone)", name)
