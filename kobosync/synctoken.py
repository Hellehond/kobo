"""The opaque token the device sends back with every /v1/library/sync call.

We stash our own high-water marks in it, plus the real Kobo store's token so
the store part of the sync can continue where it left off.
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, replace
from typing import Dict, Mapping

log = logging.getLogger(__name__)

SYNC_TOKEN_HEADER = "x-kobo-synctoken"
VERSION = "1-1-0"
_FLOAT_FIELDS = ("books_last_modified", "books_last_created", "archive_last_modified",
                 "reading_state_last_modified", "tags_last_modified")


@dataclass
class SyncToken:
    raw_kobo_store_token: str = ""
    books_last_created: float = 0.0
    books_last_modified: float = 0.0
    archive_last_modified: float = 0.0
    reading_state_last_modified: float = 0.0
    tags_last_modified: float = 0.0
    books_last_id: int = -1

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> "SyncToken":
        header = headers.get(SYNC_TOKEN_HEADER, "") or ""
        header = header.strip()
        if not header:
            return cls()
        # A device that was talking to the real store sends Kobo's own token,
        # which has the shape <base64>.<base64>.  Keep it for the store calls.
        if "." in header:
            return cls(raw_kobo_store_token=header)
        try:
            padded = header + "=" * (-len(header) % 4)
            payload = json.loads(base64.b64decode(padded))
            data = payload["data"]
            token = cls(raw_kobo_store_token=str(data.get("raw_kobo_store_token", "")))
            for name in _FLOAT_FIELDS:
                setattr(token, name, float(data.get(name, 0.0) or 0.0))
            token.books_last_id = int(data.get("books_last_id", -1))
            return token
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            log.warning("Ignoring malformed sync token (%s); starting from scratch", exc)
            return cls()

    def copy(self) -> "SyncToken":
        return replace(self)

    def build(self) -> str:
        payload = {
            "version": VERSION,
            "data": {
                "raw_kobo_store_token": self.raw_kobo_store_token,
                "books_last_modified": self.books_last_modified,
                "books_last_created": self.books_last_created,
                "archive_last_modified": self.archive_last_modified,
                "reading_state_last_modified": self.reading_state_last_modified,
                "tags_last_modified": self.tags_last_modified,
                "books_last_id": self.books_last_id,
            },
        }
        return base64.b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")

    def to_headers(self, headers: Dict[str, str]) -> None:
        headers[SYNC_TOKEN_HEADER] = self.build()
