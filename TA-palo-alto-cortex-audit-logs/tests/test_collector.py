import pytest

from cortex_audit.client import CortexApiError, CortexAuditClient
from cortex_audit.collector import (
    AGENT_REPORTS,
    DEFAULT_LOOKBACK_MS,
    MANAGEMENT_LOGS,
    collect,
    event_time_seconds,
    parse_start_time,
)
from fakes import FakeCortex, FakeResponse, MemoryCheckpoints

HOUR = 3_600_000
NOW = 1_762_400_000_000  # fixed "now" in ms


def client(session):
    return CortexAuditClient("api-t.example.com", "1", "k", session=session,
                             sleep=lambda s: None, min_request_interval=0)


def run(session, store, **kw):
    out = []
    kw.setdefault("now_ms", NOW)
    kw.setdefault("delay_ms", 0)
    stats = collect(client(session), kw.pop("endpoint", MANAGEMENT_LOGS), store, "k",
                    lambda r, t: out.append((r, t)), **kw)
    return stats, out


def mgmt(ts, i=0):
    return {"AUDIT_ID": i, "AUDIT_INSERT_TIME": ts}


def test_parse_start_time():
    assert parse_start_time("1970-01-01T00:00:10Z") == 10_000
    assert parse_start_time("") is None and parse_start_time(None) is None
    with pytest.raises(ValueError):
        parse_start_time("2026-11-01 00:00:00")


def test_event_time():
    assert event_time_seconds({"T": 1565074114053}, "T") == 1565074114.053
    assert event_time_seconds({"T": 1565074114053.0}, "T") == 1565074114.053
    assert event_time_seconds({"T": None}, "T") is None
    assert event_time_seconds({}, "T") is None


def test_first_run_default_lookback_and_hour_windows():
    records = [mgmt(NOW - DEFAULT_LOOKBACK_MS + i * HOUR, i) for i in range(24)]
    store = MemoryCheckpoints()
    stats, out = run(FakeCortex(records, "AUDIT_INSERT_TIME"), store)
    assert stats.events == 24 and stats.windows == 25  # 24h + the final 1 ms edge
    assert store.get("k")["last_end_ms"] == NOW
    # checkpoint advanced once per window, monotonically
    ends = [w[1]["last_end_ms"] for w in store.writes]
    assert ends == sorted(ends) and len(ends) == stats.windows


def test_no_duplicates_or_gaps_across_runs_at_boundaries():
    # records exactly on window edges and on the checkpoint boundary
    records = [mgmt(t, t) for t in range(NOW - 2 * HOUR, NOW + 2 * HOUR, 7 * 60_000)]
    records += [mgmt(NOW - HOUR, -1), mgmt(NOW, -2), mgmt(NOW + 1, -3)]
    api = FakeCortex(records, "AUDIT_INSERT_TIME")
    store = MemoryCheckpoints()
    _, first = run(api, store, start_time_ms=NOW - 2 * HOUR)
    _, second = run(api, store, now_ms=NOW + 2 * HOUR)
    seen = [r["AUDIT_ID"] for r, _ in first + second]
    expected = [r["AUDIT_ID"] for r in records if r["AUDIT_INSERT_TIME"] <= NOW + 2 * HOUR]
    assert sorted(seen) == sorted(expected)
    assert len(seen) == len(set(seen))


def test_delay_keeps_behind_now():
    records = [mgmt(NOW - 30_000, 1), mgmt(NOW - 120_000, 2)]
    store = MemoryCheckpoints()
    _, out = run(FakeCortex(records, "AUDIT_INSERT_TIME"), store,
                 start_time_ms=NOW - HOUR, delay_ms=60_000)
    assert [r["AUDIT_ID"] for r, _ in out] == [2]
    assert store.get("k")["last_end_ms"] == NOW - 60_000


def test_nothing_to_do_when_caught_up():
    store = MemoryCheckpoints()
    store.update("k", {"last_end_ms": NOW})
    api = FakeCortex([], "AUDIT_INSERT_TIME")
    stats, _ = run(api, store)
    assert stats.windows == 0 and api.calls == []


def test_failure_mid_window_keeps_previous_checkpoint():
    records = [mgmt(NOW - 2 * HOUR + i, i) for i in range(150)]  # all in first window
    api = FakeCortex(records, "AUDIT_INSERT_TIME")
    store = MemoryCheckpoints()
    store.update("k", {"last_end_ms": NOW - 2 * HOUR - 1})
    first_page = api.post("x", {"request_data": {
        "filters": [{"field": "timestamp", "operator": "gte", "value": NOW - 2 * HOUR}],
        "search_from": 0, "search_to": 100}}, verify=True)
    api.calls.clear()
    api.queued = [first_page, FakeResponse(403, {"reply": {"err_msg": "no"}})]
    with pytest.raises(CortexApiError):
        run(api, store)
    assert store.get("k")["last_end_ms"] == NOW - 2 * HOUR - 1  # unchanged
    _, out = run(api, store)  # retry re-collects the window in full
    assert len(out) == 150


def test_agent_reports_sort_and_category_filter():
    records = [
        {"TIMESTAMP": float(NOW - 10), "CATEGORY": "audit", "ENDPOINTID": "a"},
        {"TIMESTAMP": float(NOW - 9), "CATEGORY": "status", "ENDPOINTID": "b"},
    ]
    api = FakeCortex(records, "TIMESTAMP")
    _, out = run(api, MemoryCheckpoints(), endpoint=AGENT_REPORTS, start_time_ms=NOW - HOUR,
                 extra_filters=[{"field": "category", "operator": "in", "value": ["audit"]}])
    assert [r["ENDPOINTID"] for r, _ in out] == ["a"]
    assert out[0][1] == (NOW - 10) / 1000.0
    assert api.calls[0]["body"]["request_data"]["sort"] == {"field": "timestamp", "keyword": "asc"}
    assert api.calls[0]["url"].endswith("/public_api/v1/audits/agents_reports")


def test_max_runtime_stops_after_a_window_and_resumes():
    store = MemoryCheckpoints()
    api = FakeCortex([], "AUDIT_INSERT_TIME")
    stats, _ = run(api, store, start_time_ms=NOW - 5 * HOUR, max_runtime_s=0)
    assert stats.windows == 1 and stats.stopped_early
    assert store.get("k")["last_end_ms"] == NOW - 4 * HOUR - 1
    stats, _ = run(api, store)
    assert store.get("k")["last_end_ms"] == NOW and not stats.stopped_early
