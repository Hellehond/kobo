"""Download Bokmålsordboka articles from the ordbøkene.no API into a local cache.

The cache is an SQLite file. A later run only downloads articles that are new
or changed since the previous run, using the timestamps in the article list.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import urllib.error
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

log = logging.getLogger("nbdict")

API = "https://ord.uib.no/bm"
USER_AGENT = "kobosync-dictionary-builder/1.0 (+https://github.com/Hellehond/kobo)"
WORKERS = 4  # be gentle with a free public service


def _get(url: str, attempts: int = 5) -> bytes:
    delay = 2.0
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise
            if attempt == attempts:
                raise
            log.warning("%s: HTTP %s, retrying in %.0fs", url, exc.code, delay)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt == attempts:
                raise
            log.warning("%s: %s, retrying in %.0fs", url, exc, delay)
        time.sleep(delay)
        delay *= 2
    raise RuntimeError("unreachable")


class Cache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(path))
        self.con.execute("CREATE TABLE IF NOT EXISTS articles (id INTEGER PRIMARY KEY, updated TEXT, data BLOB)")
        self.con.execute("CREATE TABLE IF NOT EXISTS files (name TEXT PRIMARY KEY, data BLOB)")

    def known(self) -> Dict[int, str]:
        return dict(self.con.execute("SELECT id, updated FROM articles"))

    def put(self, article_id: int, updated: str, data: Optional[bytes]) -> None:
        blob = zlib.compress(data, 9) if data is not None else None
        self.con.execute("INSERT OR REPLACE INTO articles (id, updated, data) VALUES (?, ?, ?)",
                         (article_id, updated, blob))

    def delete_except(self, keep: Iterable[int]) -> int:
        keep = set(keep)
        gone = [i for (i,) in self.con.execute("SELECT id FROM articles") if i not in keep]
        self.con.executemany("DELETE FROM articles WHERE id = ?", [(i,) for i in gone])
        return len(gone)

    def put_file(self, name: str, data: bytes) -> None:
        self.con.execute("INSERT OR REPLACE INTO files (name, data) VALUES (?, ?)", (name, data))

    def get_file(self, name: str) -> Optional[bytes]:
        row = self.con.execute("SELECT data FROM files WHERE name = ?", (name,)).fetchone()
        return row[0] if row else None

    def articles(self) -> Iterable[dict]:
        for (blob,) in self.con.execute("SELECT data FROM articles WHERE data IS NOT NULL ORDER BY id"):
            yield json.loads(zlib.decompress(blob))

    def commit(self) -> None:
        self.con.commit()


def update(cache: Cache, limit: Optional[int] = None, workers: int = WORKERS) -> Tuple[int, int]:
    """Bring the cache up to date. Returns (downloaded, total)."""
    listing = json.loads(_get(f"{API}/fil/article.json"))
    cache.put_file("concepts.json", _get(f"{API}/concepts.json"))
    wanted = {int(row[0]): str(row[3]) for row in listing}
    removed = cache.delete_except(wanted)
    if removed:
        log.info("%d article(s) no longer in the dictionary", removed)
    known = cache.known()
    todo: List[Tuple[int, str]] = [(i, ts) for i, ts in wanted.items() if known.get(i) != ts]
    todo.sort()
    if limit is not None:
        todo = todo[:limit]
    log.info("%d article(s) in the dictionary, %d to download", len(wanted), len(todo))

    def fetch(item: Tuple[int, str]) -> Tuple[int, str, Optional[bytes]]:
        article_id, updated = item
        try:
            return article_id, updated, _get(f"{API}/article/{article_id}.json")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return article_id, updated, None
            raise

    done = 0
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as pool:
        for future in as_completed([pool.submit(fetch, item) for item in todo]):
            article_id, updated, data = future.result()
            cache.put(article_id, updated, data)
            done += 1
            if done % 250 == 0:
                cache.commit()
                rate = done / max(time.monotonic() - started, 1e-6)
                log.info("%d/%d downloaded (%.0f per second)", done, len(todo), rate)
    cache.commit()
    return done, len(wanted)
