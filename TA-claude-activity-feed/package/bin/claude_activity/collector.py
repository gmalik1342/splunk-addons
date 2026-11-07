"""Incremental collection of the Anthropic Activity Feed.

Follows Anthropic's "window polling" guidance for the Compliance API:

* Query closed windows ``[gte, lt)`` whose ``lt`` is at least the ingestion lag
  (default 120 s; the documented indexing lag is ~1 minute) behind now.
* Re-query an overlap (default 10 minutes) before each window so activities
  that were indexed late are still picked up, and de-duplicate on activity
  ``id`` (delivery is at-least-once).
* Page each window with ``after_id`` until ``has_more`` is false; the
  checkpoint only advances after a whole window has been written.

Checkpoint state::

    {"version": 1, "high_water": "<RFC 3339>", "recent": {"<activity id>": <created_at epoch>}}
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

DEFAULT_LAG_S = 120
MIN_LAG_S = 60
DEFAULT_OVERLAP_S = 600
WINDOW_S = 3600
PAGE_LIMIT = 1000
MAX_PAGES_PER_WINDOW = 10000
DEFAULT_LOOKBACK_S = 24 * 3600

_RFC3339 = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|z|[+-]\d{2}:\d{2})$"
)


def parse_time(value: Any) -> Optional[float]:
    """RFC 3339 -> epoch seconds (handles 'Z', offsets and >6 fractional digits)."""
    if not isinstance(value, str):
        return None
    m = _RFC3339.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second = (int(x) for x in m.groups()[:6])
    frac = float("0" + m.group(7)) if m.group(7) else 0.0
    tz = m.group(8)
    if tz in ("Z", "z"):
        offset = timedelta(0)
    else:
        sign = 1 if tz[0] == "+" else -1
        offset = sign * timedelta(hours=int(tz[1:3]), minutes=int(tz[4:6]))
    dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone(offset))
    return dt.timestamp() + frac


def format_time(epoch: float) -> str:
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_start_time(value: Optional[str]) -> Optional[float]:
    """User-supplied start time (YYYY-MM-DDThh:mm:ssZ) -> epoch, or None if empty."""
    if value in (None, ""):
        return None
    epoch = parse_time(value)
    if epoch is None:
        raise ValueError("Start Time must look like 2026-11-01T00:00:00Z.")
    return epoch


def parse_activity_types(value: Optional[str]) -> List[str]:
    if not value:
        return []
    types = [t.strip() for t in re.split(r"[,\s]+", value) if t.strip()]
    for t in types:
        if not re.match(r"^[a-z0-9_]+$", t):
            raise ValueError("Invalid activity type '{}'.".format(t))
    return types


@dataclass
class Stats:
    windows: int = 0
    pages: int = 0
    events: int = 0
    duplicates: int = 0
    high_water: Optional[str] = None
    stopped_early: bool = False


def collect(
    client: Any,
    state: Optional[Dict[str, Any]],
    emit: Callable[[Dict[str, Any], Optional[float]], None],
    save_state: Callable[[Dict[str, Any]], None],
    start_time: Optional[float] = None,
    lag_s: int = DEFAULT_LAG_S,
    overlap_s: int = DEFAULT_OVERLAP_S,
    activity_types: Optional[List[str]] = None,
    max_runtime_s: float = 3300,
    logger: Optional[logging.Logger] = None,
    clock: Callable[[], float] = time.time,
    page_limit: int = PAGE_LIMIT,
) -> Stats:
    log = logger or logging.getLogger(__name__)
    stats = Stats()
    started = clock()
    lag_s = max(int(lag_s), MIN_LAG_S)

    state = dict(state or {})
    recent: Dict[str, float] = dict(state.get("recent") or {})
    high_water = parse_time(state.get("high_water"))
    first_run = high_water is None
    if first_run:
        high_water = start_time if start_time is not None else clock() - DEFAULT_LOOKBACK_S
        high_water = float(int(high_water))

    end_limit = float(int(clock() - lag_s))
    while high_water < end_limit:
        if clock() - started > max_runtime_s:
            stats.stopped_early = True
            log.info("Stopping after %.0fs; collection resumes next run from %s", max_runtime_s, format_time(high_water))
            break
        window_end = min(high_water + WINDOW_S, end_limit)
        # Overlap only re-reads time we have already covered (never before the first start).
        query_gte = high_water if first_run and stats.windows == 0 else high_water - overlap_s
        gte, lt = format_time(query_gte), format_time(window_end)

        after_id = None
        for _ in range(MAX_PAGES_PER_WINDOW):
            page = client.list_activities(gte, lt, after_id=after_id, limit=page_limit,
                                          activity_types=activity_types)
            stats.pages += 1
            for activity in page.get("data") or []:
                if not isinstance(activity, dict):
                    continue
                aid = activity.get("id")
                created = parse_time(activity.get("created_at"))
                if aid is not None and aid in recent:
                    stats.duplicates += 1
                    continue
                emit(activity, created)
                stats.events += 1
                if aid is not None:
                    recent[aid] = created if created is not None else window_end
            if not page.get("has_more"):
                break
            next_cursor = page.get("last_id")
            if not next_cursor or next_cursor == after_id:
                log.warning("Activity Feed returned has_more without a new cursor; ending window %s..%s", gte, lt)
                break
            after_id = next_cursor
        else:
            log.warning("Window %s..%s exceeded %d pages; continuing with next window", gte, lt, MAX_PAGES_PER_WINDOW)

        high_water = window_end
        # Keep only ids that the next window's overlap can return again.
        cutoff = high_water - overlap_s - 60
        recent = {k: v for k, v in recent.items() if v >= cutoff}
        state = {"version": 1, "high_water": format_time(high_water), "recent": recent}
        save_state(state)
        stats.windows += 1
        stats.high_water = state["high_water"]

    return stats
