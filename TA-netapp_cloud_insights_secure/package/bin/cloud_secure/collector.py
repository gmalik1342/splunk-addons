"""Collect Workload Security alerts without re-ingesting unchanged ones.

The alerts API returns alerts from a rolling time range (``ONE_WEEK``),
paged with ``limit``/``offset``. Each run pages through all of them and emits
an alert only if its ``id`` is new or its content changed since it was last
emitted (for example ``status`` moved from New to Resolved, or an automated
action ran). State is ``{id: [alertTimestamp_ms, fingerprint]}``; entries older
than the API window are pruned so the state stays bounded.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

PAGE_SIZE = 1000
MAX_PAGES = 100
TIME_RANGE = "ONE_WEEK"
# Keep state a little longer than the API window so nothing at the edge re-emits.
STATE_RETENTION_MS = 8 * 24 * 3600 * 1000


@dataclass
class Stats:
    pages: int = 0
    seen: int = 0
    new: int = 0
    updated: int = 0
    stopped_reason: str = ""


def fingerprint(alert: Dict[str, Any]) -> str:
    raw = json.dumps(alert, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def alert_id(alert: Dict[str, Any]) -> str:
    value = alert.get("id")
    if value not in (None, ""):
        return str(value)
    # No id: fall back to a content hash (such an alert is never "updated").
    return "fp:" + fingerprint(alert)


def alert_time_ms(alert: Dict[str, Any]) -> Optional[int]:
    try:
        return int(alert.get("alertTimestamp"))
    except (TypeError, ValueError):
        return None


def collect(
    client: Any,
    state: Optional[Dict[str, Any]],
    emit: Callable[[Dict[str, Any], Optional[float]], None],
    logger: Optional[logging.Logger] = None,
    page_size: int = PAGE_SIZE,
    max_pages: int = MAX_PAGES,
    now_ms: Optional[int] = None,
) -> Tuple[Dict[str, Any], Stats]:
    """Run one collection. Returns ``(new_state, stats)``; the caller saves the state."""
    log = logger or logging.getLogger(__name__)
    seen: Dict[str, List[Any]] = dict((state or {}).get("alerts") or {})
    stats = Stats()
    run_ids = set()
    offset = 0

    while True:
        if stats.pages >= max_pages:
            stats.stopped_reason = "max_pages"
            log.warning("Stopped after %d pages; remaining alerts are collected next run.", max_pages)
            break
        body = client.get_alerts(limit=page_size, offset=offset, time_range=TIME_RANGE)
        results = body.get("results") or []
        stats.pages += 1

        added_this_page = 0
        for alert in results:
            if not isinstance(alert, dict):
                continue
            aid = alert_id(alert)
            if aid in run_ids:
                continue  # overlap between pages
            run_ids.add(aid)
            added_this_page += 1
            stats.seen += 1
            fp = fingerprint(alert)
            ts = alert_time_ms(alert)
            previous = seen.get(aid)
            if previous is None or previous[1] != fp:
                emit(alert, ts / 1000.0 if ts is not None else None)
                if previous is None:
                    stats.new += 1
                else:
                    stats.updated += 1
            seen[aid] = [ts if ts is not None else (previous[0] if previous else None), fp]

        if not results:
            stats.stopped_reason = "empty_page"
            break
        if offset > 0 and added_this_page == 0:
            # Nothing on this page was new to this run: the API ignored offset.
            stats.stopped_reason = "offset_ignored"
            log.warning("API returned an already-seen page at offset %d; stopping.", offset)
            break
        offset += len(results)
        count = body.get("count")
        if len(results) < page_size:
            stats.stopped_reason = "last_page"
            break
        if isinstance(count, int) and count > len(results) and offset >= count:
            stats.stopped_reason = "count_reached"
            break

    now = int(time.time() * 1000) if now_ms is None else now_ms
    cutoff = now - STATE_RETENTION_MS
    pruned = {k: v for k, v in seen.items() if v[0] is None or v[0] >= cutoff}
    return {"version": 1, "alerts": pruned}, stats

