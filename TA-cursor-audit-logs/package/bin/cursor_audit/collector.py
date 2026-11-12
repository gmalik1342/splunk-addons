"""Incremental collection of Cursor audit logs.

* Query closed windows ``[start, end]`` (epoch ms) at most ``WINDOW_S`` long,
  ending at least the ingestion delay (default 300 s) behind now. Cursor's
  docs say to "page through consecutive windows" for longer periods.
* Re-query an overlap (default 10 minutes) before each window and
  de-duplicate on ``event_id``. This also covers whether the API treats the
  window edges as inclusive or exclusive.
* Page each window with ``page``/``pageSize`` (oldest first) until
  ``hasNextPage`` is false. Because the window is closed and in the past,
  page offsets are stable.
* The checkpoint only advances after a whole window has been written.

Checkpoint state::

    {"version": 1, "high_water_ms": <epoch ms>, "recent": {"<event_id>": <epoch s>}}
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

DEFAULT_LAG_S = 300
MIN_LAG_S = 60
DEFAULT_OVERLAP_S = 600
WINDOW_S = 6 * 3600
PAGE_SIZE = 500
MAX_PAGES_PER_WINDOW = 2000
DEFAULT_LOOKBACK_S = 24 * 3600

_RFC3339 = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|z|[+-]\d{2}:\d{2})$"
)
_EVENT_TYPE = re.compile(r"^[a-z0-9_.:-]+$")


def parse_time(value: Any) -> Optional[float]:
    """RFC 3339 -> epoch seconds (handles 'Z', offsets and long fractions)."""
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
    """User-supplied start time (YYYY-MM-DDThh:mm:ssZ) -> epoch seconds, or None if empty."""
    if value in (None, ""):
        return None
    epoch = parse_time(value)
    if epoch is None:
        raise ValueError("Start Time must look like 2026-11-01T00:00:00Z.")
    return epoch


def parse_event_types(value: Optional[str]) -> List[str]:
    if not value:
        return []
    types = [t.strip() for t in re.split(r"[,\s]+", value) if t.strip()]
    for t in types:
        if not _EVENT_TYPE.match(t):
            raise ValueError("Invalid event type '{}'.".format(t))
    return types


def event_time(event: Dict[str, Any]) -> Optional[float]:
    value = event.get("timestamp")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value / 1000.0 if value > 1e11 else float(value)
    return parse_time(value)


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
    event_types: Optional[List[str]] = None,
    max_runtime_s: float = 3300,
    logger: Optional[logging.Logger] = None,
    clock: Callable[[], float] = time.time,
    page_size: int = PAGE_SIZE,
    window_s: int = WINDOW_S,
) -> Stats:
    log = logger or logging.getLogger(__name__)
    stats = Stats()
    started = clock()
    lag_s = max(int(lag_s), MIN_LAG_S)

    state = dict(state or {})
    recent: Dict[str, float] = dict(state.get("recent") or {})
    hw_ms = state.get("high_water_ms")
    first_run = hw_ms is None
    if first_run:
        start = start_time if start_time is not None else clock() - DEFAULT_LOOKBACK_S
        high_water = float(int(start))
    else:
        high_water = int(hw_ms) / 1000.0

    end_limit = float(int(clock() - lag_s))
    while high_water < end_limit:
        if clock() - started > max_runtime_s:
            stats.stopped_early = True
            log.info("Stopping after %.0fs; collection resumes next run from %s",
                     max_runtime_s, format_time(high_water))
            break
        window_end = min(high_water + window_s, end_limit)
        # Overlap only re-reads time already covered (never before the first start).
        query_start = high_water if first_run and stats.windows == 0 else high_water - overlap_s
        start_ms, end_ms = int(query_start * 1000), int(window_end * 1000)

        page_no = 1
        for _ in range(MAX_PAGES_PER_WINDOW):
            page = client.list_events(start_ms, end_ms, page=page_no, page_size=page_size,
                                      event_types=event_types)
            stats.pages += 1
            events = [e for e in page.get("events") or [] if isinstance(e, dict)]
            for event in events:
                eid = event.get("event_id")
                created = event_time(event)
                if eid is not None and eid in recent:
                    stats.duplicates += 1
                    continue
                emit(event, created)
                stats.events += 1
                if eid is not None:
                    recent[str(eid)] = created if created is not None else window_end
            pagination = page.get("pagination") or {}
            if not events or not pagination.get("hasNextPage"):
                break
            page_no += 1
        else:
            log.warning("Window %s..%s exceeded %d pages; continuing with the next window",
                        format_time(query_start), format_time(window_end), MAX_PAGES_PER_WINDOW)

        high_water = window_end
        # Keep only ids that the next window's overlap can return again.
        cutoff = high_water - overlap_s - 60
        recent = {k: v for k, v in recent.items() if v >= cutoff}
        state = {"version": 1, "high_water_ms": int(high_water * 1000), "recent": recent}
        save_state(state)
        stats.windows += 1
        stats.high_water = format_time(high_water)

    return stats
