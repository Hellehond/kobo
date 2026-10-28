from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

KOBO_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def now() -> float:
    return time.time()


def to_kobo_timestamp(epoch: Optional[float]) -> str:
    """Format an epoch value the way the Kobo API expects (UTC, second precision)."""
    if epoch is None:
        epoch = 0.0
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).strftime(KOBO_TIMESTAMP_FORMAT)


def parse_kobo_timestamp(value) -> Optional[float]:
    """Parse timestamps as sent by the device, e.g. 2024-01-02T03:04:05Z or
    2024-01-02T03:04:05.1234567Z.  Returns an epoch float or None."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    # Strip sub-second digits beyond what fromisoformat accepts.
    if "." in text:
        head, _, frac = text.partition(".")
        frac = "".join(ch for ch in frac if ch.isdigit())[:6]
        text = head + ("." + frac if frac else "")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def parse_loose_date(value) -> Optional[float]:
    """Parse the various date forms found in EPUB metadata (full ISO, date only, year)."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    for candidate in (text, text.rstrip("Z"), text[:19], text[:10], text[:7] + "-01", text[:4] + "-01-01"):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    return None
