"""Time-windowed, checkpointed collection for the Cortex audit endpoints.

Each run collects closed windows [start, end] (epoch ms, inclusive) from the
last checkpoint up to ``now - delay``. The checkpoint is advanced only after a
window has been fully paged and written, so a failed run re-collects at most
one window (at-least-once delivery) and never skips data.
"""

from __future__ import annotations

import calendar
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol

from .client import CortexAuditClient

CHECKPOINT_VERSION = 1
DEFAULT_LOOKBACK_MS = 24 * 60 * 60 * 1000
DEFAULT_WINDOW_MS = 60 * 60 * 1000


@dataclass(frozen=True)
class AuditEndpoint:
    input_type: str
    path: str
    time_field: str
    sourcetype: str
    sort: Optional[Dict[str, str]] = None


MANAGEMENT_LOGS = AuditEndpoint(
    input_type="cortex_audit_management_logs",
    path="/public_api/v1/audits/management_logs",
    time_field="AUDIT_INSERT_TIME",
    sourcetype="cortex:audit:management_logs",
    # The documented sort fields for this endpoint do not include timestamp,
    # so the default order is used; windowing makes ordering irrelevant.
    sort=None,
)

AGENT_REPORTS = AuditEndpoint(
    input_type="cortex_audit_agent_reports",
    path="/public_api/v1/audits/agents_reports",
    time_field="TIMESTAMP",
    sourcetype="cortex:audit:agent_reports",
    sort={"field": "timestamp", "keyword": "asc"},
)


class CheckpointStore(Protocol):
    def get(self, key: str) -> Optional[Dict[str, Any]]: ...

    def update(self, key: str, state: Dict[str, Any]) -> None: ...


@dataclass
class RunStats:
    events: int = 0
    windows: int = 0
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    stopped_early: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)


def parse_start_time(value: Optional[str]) -> Optional[int]:
    """Parse ``YYYY-MM-DDThh:mm:ssZ`` (UTC) into epoch milliseconds."""
    if not value or not str(value).strip():
        return None
    try:
        parsed = time.strptime(str(value).strip(), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError("Start Time must use the format YYYY-MM-DDThh:mm:ssZ (UTC).") from exc
    return calendar.timegm(parsed) * 1000


def event_time_seconds(record: Dict[str, Any], time_field: str) -> Optional[float]:
    """Return the record timestamp in epoch seconds, or None if unusable."""
    value = record.get(time_field)
    try:
        millis = float(value)
    except (TypeError, ValueError):
        return None
    if millis <= 0:
        return None
    return millis / 1000.0


def resolve_start_ms(
    checkpoint: Optional[Dict[str, Any]], start_time_ms: Optional[int], now_ms: int
) -> int:
    if checkpoint and checkpoint.get("last_end_ms") is not None:
        return int(checkpoint["last_end_ms"]) + 1
    if start_time_ms is not None:
        return start_time_ms
    return now_ms - DEFAULT_LOOKBACK_MS


def collect(
    client: CortexAuditClient,
    endpoint: AuditEndpoint,
    checkpoints: CheckpointStore,
    checkpoint_key: str,
    emit: Callable[[Dict[str, Any], Optional[float]], None],
    start_time_ms: Optional[int] = None,
    delay_ms: int = 60_000,
    window_ms: int = DEFAULT_WINDOW_MS,
    extra_filters: Optional[List[Dict[str, Any]]] = None,
    now_ms: Optional[int] = None,
    max_runtime_s: Optional[float] = None,
    logger: Optional[logging.Logger] = None,
) -> RunStats:
    """Collect all records from the checkpoint up to ``now - delay``.

    ``emit(record, event_time_seconds)`` is called for each record.
    """
    log = logger or logging.getLogger(__name__)
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    started = time.monotonic()
    stats = RunStats()

    checkpoint = checkpoints.get(checkpoint_key)
    start_ms = resolve_start_ms(checkpoint, start_time_ms, now_ms)
    target_end_ms = now_ms - max(0, int(delay_ms))
    stats.start_ms = start_ms

    if start_ms > target_end_ms:
        log.info("Nothing to collect yet; next window starts at %d", start_ms)
        return stats

    window_start = start_ms
    while window_start <= target_end_ms:
        window_end = min(window_start + window_ms - 1, target_end_ms)
        count = 0
        for record in client.iter_window(
            endpoint.path, window_start, window_end, extra_filters, endpoint.sort
        ):
            emit(record, event_time_seconds(record, endpoint.time_field))
            count += 1
        checkpoints.update(
            checkpoint_key,
            {"version": CHECKPOINT_VERSION, "last_end_ms": window_end, "updated_ms": now_ms},
        )
        stats.events += count
        stats.windows += 1
        stats.end_ms = window_end
        log.debug("Window %d-%d done: %d events", window_start, window_end, count)
        window_start = window_end + 1

        if max_runtime_s is not None and time.monotonic() - started > max_runtime_s:
            if window_start <= target_end_ms:
                stats.stopped_early = True
                log.info("Run time limit reached; resuming from %d on the next run", window_start)
            break
    return stats
