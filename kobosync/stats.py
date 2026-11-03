"""Reading statistics from the reading states the devices report."""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .db import Database

# One report never adds more than this, whatever the device says.
MAX_MINUTES_PER_REPORT = 600

MONTHS = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus",
          "september", "oktober", "november", "december"]


def minutes_added(previous: Optional[int], new: Optional[int], seconds_since_last: Optional[float]) -> int:
    """Reading time a report adds.

    The Kobo reports the total time spent in a book, and the devices share that
    total through the sync.  The difference with the last known total is the
    time read since, capped by the time that has passed.
    """
    if new is None:
        return 0
    added = new - previous if previous is not None else new
    limit = MAX_MINUTES_PER_REPORT
    if seconds_since_last is not None and previous is not None:
        limit = min(limit, int(seconds_since_last // 60) + 5)
    return max(0, min(added, limit))


def zone(name: str):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


@dataclass
class Month:
    name: str
    finished: int = 0
    minutes: int = 0


@dataclass
class YearStats:
    year: int
    goal: int
    finished: List[Dict[str, Any]] = field(default_factory=list)
    reading: List[Dict[str, Any]] = field(default_factory=list)
    months: List[Month] = field(default_factory=list)
    minutes: int = 0
    years: List[int] = field(default_factory=list)
    expected_by_now: Optional[float] = None

    @property
    def max_month_minutes(self) -> int:
        return max([m.minutes for m in self.months] + [1])

    @property
    def max_month_finished(self) -> int:
        return max([m.finished for m in self.months] + [1])


def year_stats(db: Database, year: Optional[int], goal: int, tz_name: str) -> YearStats:
    tz = zone(tz_name)
    now = datetime.now(tz)
    year = year or now.year

    def local(ts: float) -> datetime:
        return datetime.fromtimestamp(ts, tz)

    books = {b["id"]: b for b in db.overview()}
    events = db.reading_events()

    started: Dict[int, float] = {}
    finished_at: Dict[int, float] = {}
    for e in events:
        if e["book_id"] not in started and (e["status"] in ("Reading", "Finished") or (e["progress"] or 0) > 0):
            started[e["book_id"]] = e["ts"]
        if e["status"] == "Finished" and e["book_id"] not in finished_at:
            finished_at[e["book_id"]] = e["ts"]
    # Books finished before statistics were kept still count, by the date the
    # status last changed.
    for book in books.values():
        if book["status"] == "Finished" and book["id"] not in finished_at and book.get("status_modified"):
            finished_at[book["id"]] = book["status_modified"]

    years = {now.year}
    years.update(local(ts).year for ts in finished_at.values())
    years.update(local(e["ts"]).year for e in events)

    stats = YearStats(year=year, goal=goal, years=sorted(years, reverse=True),
                      months=[Month(name) for name in MONTHS])
    for e in events:
        when = local(e["ts"])
        if when.year == year and e["minutes_added"]:
            stats.months[when.month - 1].minutes += e["minutes_added"]
            stats.minutes += e["minutes_added"]

    for book_id, ts in finished_at.items():
        book = books.get(book_id)
        when = local(ts)
        if book is None or when.year != year:
            continue
        stats.months[when.month - 1].finished += 1
        begin = started.get(book_id)
        stats.finished.append({
            "title": book["title"],
            "authors": book["authors"],
            "started": local(begin) if begin and begin <= ts else None,
            "finished": when,
            "days": max(1, (when.date() - local(begin).date()).days + 1) if begin and begin <= ts else None,
            "minutes": book.get("spent_reading_minutes"),
        })
    stats.finished.sort(key=lambda b: b["finished"], reverse=True)

    stats.reading = [b for b in books.values() if b["status"] == "Reading" and not b["archived"]]

    if goal and year == now.year:
        days = 366 if calendar.isleap(year) else 365
        stats.expected_by_now = goal * now.timetuple().tm_yday / days
    return stats


def format_minutes(minutes: Optional[int]) -> str:
    if not minutes:
        return "0 min"
    hours, rest = divmod(int(minutes), 60)
    if not hours:
        return f"{rest} min"
    return f"{hours} u {rest:02d} min"
