"""Incremental collection of LangSmith audit logs.

* Query closed windows ``[start, end]`` (epoch ms, both inclusive in the API)
  at most ``WINDOW_S`` long, ending at least the ingestion delay (default
  300 s) behind now. LangSmith's own SIEM guidance is to pull the previous
  hour on a schedule.
* Re-query an overlap (default 10 minutes) before each window and
  de-duplicate on the event id (OCSF ``metadata.uid``). Inclusive edges and
  late-recorded events are therefore neither missed nor ingested twice.
* Page each window with ``cursor`` until the API returns no cursor.
* The checkpoint only advances after a whole window has been written.

Checkpoint state::

    {"version": 1, "high_water_ms": <epoch ms>, "recent": {"<event id>": <epoch s>}}
"""

from __future__ import annotations

import hashlib
import json
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
PAGE_LIMIT = 100
MAX_PAGES_PER_WINDOW = 10000
DEFAULT_LOOKBACK_S = 24 * 3600

_RFC3339 = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|z|[+-]\d{2}:\d{2})?$"
)
_OPERATION = re.compile(r"^[a-z0-9_]+$")


def parse_time(value: Any) -> Optional[float]:
    """RFC 3339 / ISO 8601 -> epoch seconds. A missing offset is treated as UTC."""
    if not isinstance(value, str):
        return None
    m = _RFC3339.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second = (int(x) for x in m.groups()[:6])
    frac = float("0" + m.group(7)) if m.group(7) else 0.0
    tz = m.group(8)
    if tz in (None, "Z", "z"):
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
    if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", value.strip()):
        raise ValueError("Start Time must look like 2026-11-01T00:00:00Z.")
    return parse_time(value)


def parse_operations(value: Optional[str]) -> List[str]:
    if not value:
        return []
    ops = [t.strip() for t in re.split(r"[,\s]+", value) if t.strip()]
    for op in ops:
        if not _OPERATION.match(op):
            raise ValueError("Invalid operation '{}'.".format(op))
    return ops


def _epoch_number(value: Any) -> Optional[float]:
    """OCSF timestamps are epoch milliseconds; also accept seconds and microseconds."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    if value > 1e14:      # microseconds
        return value / 1e6
    if value > 1e11:      # milliseconds
        return value / 1e3
    return float(value)   # seconds


def event_time(item: Dict[str, Any]) -> Optional[float]:
    t = _epoch_number(item.get("time"))
    if t is not None:
        return t
    original = ((item.get("unmapped") or {}).get("original_audit_log") or {})
    return parse_time(original.get("request_time"))


def event_id(item: Dict[str, Any]) -> str:
    uid = (item.get("metadata") or {}).get("uid")
    if uid not in (None, ""):
        return str(uid)
    original = ((item.get("unmapped") or {}).get("original_audit_log") or {})
    if original.get("id") not in (None, ""):
        return str(original["id"])
    raw = json.dumps(item, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


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
    operations: Optional[List[str]] = None,
    max_runtime_s: float = 3300,
    logger: Optional[logging.Logger] = None,
    clock: Callable[[], float] = time.time,
    page_limit: int = PAGE_LIMIT,
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

        cursor = None
        for _ in range(MAX_PAGES_PER_WINDOW):
            page = client.list_audit_logs(start_ms, end_ms, cursor=cursor, limit=page_limit,
                                          operations=operations)
            stats.pages += 1
            for item in page.get("items") or []:
                if not isinstance(item, dict):
                    continue
                eid = event_id(item)
                created = event_time(item)
                if eid in recent:
                    stats.duplicates += 1
                    continue
                emit(item, created)
                stats.events += 1
                recent[eid] = created if created is not None else window_end
            next_cursor = page.get("cursor")
            if not next_cursor:
                break
            if next_cursor == cursor:
                log.warning("Audit log API returned the same cursor twice; ending window %s..%s",
                            format_time(query_start), format_time(window_end))
                break
            cursor = next_cursor
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
