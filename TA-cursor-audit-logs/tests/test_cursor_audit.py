import json
import os
import re

import pytest

import cursor_audit
from cursor_audit.client import MAX_PAGE_SIZE, AuditLogClient, CursorApiError, build_proxies
from cursor_audit.collector import (
    DEFAULT_LOOKBACK_S,
    collect,
    event_time,
    format_time,
    parse_event_types,
    parse_start_time,
    parse_time,
)

ROOT = os.path.join(os.path.dirname(__file__), "..")
T0 = 1_800_000_000  # 2027-01-15T08:00:00Z


def ev(i, t, typ="add_user"):
    iso = "{}.{:03d}Z".format(format_time(t)[:-1], 0)
    return {"event_id": "evt-{:05d}".format(i), "timestamp": iso, "ip_address": "203.0.113.7",
            "user_email": "admin@example.com", "event_type": typ, "application_type": "cursor",
            "event_data": {"user_email": "dev{}@example.com".format(i), "role": "member"}}


class FakeCursor:
    """Oldest-first, page-numbered audit log with inclusive [startTime, endTime] in ms.

    Events only become visible once 'recorded' (late recording simulates lag).
    """

    def __init__(self, events):
        self.events = events  # list of (event, recorded_at)
        self.now = T0
        self.calls = []

    def list_events(self, start_ms, end_ms, page=1, page_size=500, event_types=None):
        self.calls.append((start_ms, end_ms, page, page_size, event_types))
        assert end_ms - start_ms <= 30 * 24 * 3600 * 1000
        rows = [e for e, rec in self.events
                if rec <= self.now and start_ms <= parse_time(e["timestamp"]) * 1000 <= end_ms
                and (not event_types or e["event_type"] in event_types)]
        rows.sort(key=lambda e: (parse_time(e["timestamp"]), e["event_id"]))
        chunk = rows[(page - 1) * page_size: page * page_size]
        total_pages = max(1, -(-len(rows) // page_size))
        return {"events": chunk,
                "pagination": {"page": page, "pageSize": page_size, "totalCount": len(rows),
                               "totalPages": total_pages, "hasNextPage": page < total_pages,
                               "hasPreviousPage": page > 1},
                "params": {"teamId": 1, "startDate": start_ms, "endDate": end_ms}}


def run(api, state, **kw):
    out, saved = [], []
    stats = collect(api, state, lambda e, t: out.append((e["event_id"], t)), saved.append,
                    clock=lambda: api.now, **kw)
    return (saved[-1] if saved else state), stats, out


# --- collector -----------------------------------------------------------------

def test_first_run_lookback_lag_and_event_time():
    api = FakeCursor([(ev(1, T0 - 3000), 0), (ev(2, T0 - 100), 0)])  # 2nd inside the 300 s lag
    state, stats, out = run(api, None)
    assert [i for i, _ in out] == ["evt-00001"] and out[0][1] == T0 - 3000
    assert state["high_water_ms"] == (T0 - 300) * 1000
    assert api.calls[0][0] == (T0 - DEFAULT_LOOKBACK_S) * 1000  # no overlap before the first start


def test_windows_of_six_hours_and_checkpoint_per_window():
    api = FakeCursor([(ev(i, T0 - 20 * 3600 + i * 600), 0) for i in range(100)])
    saved = []
    stats = collect(api, None, lambda e, t: None, saved.append, start_time=T0 - 20 * 3600,
                    clock=lambda: api.now)
    assert stats.windows == 4 and stats.events == 100
    assert [s["high_water_ms"] for s in saved] == sorted(s["high_water_ms"] for s in saved)


def test_inclusive_edges_and_overlap_never_duplicate():
    # One event exactly on a window edge: inclusive API bounds return it twice.
    edge = T0 - 3600
    api = FakeCursor([(ev(1, edge), 0), (ev(2, edge - 10), 0), (ev(3, edge + 10), 0)])
    state, _, out1 = run(api, None, start_time=edge - 1000, window_s=1000)
    _, stats2, out2 = run(api, state, start_time=None)
    ids = [i for i, _ in out1 + out2]
    assert sorted(ids) == ["evt-00001", "evt-00002", "evt-00003"] and len(ids) == len(set(ids))


def test_late_recorded_event_is_picked_up_by_overlap_once():
    early = ev(1, T0 - 1000)
    late = ev(2, T0 - 400)                          # inside the first window...
    api = FakeCursor([(early, 0), (late, T0 + 100)])  # ...but recorded after it closed
    state, _, out1 = run(api, None, start_time=T0 - 2000)
    assert [i for i, _ in out1] == ["evt-00001"]
    api.now = T0 + 300
    state, _, out2 = run(api, state)
    assert [i for i, _ in out2] == ["evt-00002"]
    api.now = T0 + 600
    _, stats3, out3 = run(api, state)
    assert out3 == [] and stats3.duplicates >= 1


def test_page_number_pagination():
    api = FakeCursor([(ev(i, T0 - 3000 + i), 0) for i in range(23)])
    _, stats, out = run(api, None, start_time=T0 - 3500, page_size=10)
    assert len(out) == 23 and len({i for i, _ in out}) == 23
    assert [c[2] for c in api.calls] == [1, 2, 3]


def test_event_type_filter_passed():
    api = FakeCursor([(ev(1, T0 - 3000, "login"), 0), (ev(2, T0 - 2000), 0)])
    _, _, out = run(api, None, start_time=T0 - 3500, event_types=["login"])
    assert [i for i, _ in out] == ["evt-00001"] and api.calls[0][4] == ["login"]


def test_recent_ids_pruned_to_overlap():
    # one event a minute up to just before the lag edge (T0 - 300)
    api = FakeCursor([(ev(i, T0 - 5 * 3600 + i * 60), 0) for i in range(295)])
    state, _, out = run(api, None, start_time=T0 - 5 * 3600)
    assert len(out) == 295
    hw = state["high_water_ms"] / 1000
    assert state["recent"] and all(v >= hw - 600 - 60 for v in state["recent"].values())


def test_stops_on_max_runtime_and_lag_floor():
    api = FakeCursor([])
    stats = collect(api, None, lambda e, t: None, lambda s: None, start_time=T0 - 10 * 3600,
                    clock=lambda: T0, max_runtime_s=-1)
    assert stats.stopped_early and stats.windows == 0
    api = FakeCursor([(ev(1, T0 - 30), 0)])
    _, _, out = run(api, None, start_time=T0 - 600, lag_s=0)
    assert out == []  # lag never below 60 s


def test_parsers():
    assert parse_time("2024-01-15T12:30:00.000Z") == parse_time("2024-01-15T14:30:00+02:00")
    assert event_time({"timestamp": "2024-01-15T12:30:00.250Z"}) % 1 == pytest.approx(0.25)
    assert event_time({"timestamp": 1705321800000}) == 1705321800.0
    assert event_time({"timestamp": None}) is None
    assert parse_start_time("") is None
    with pytest.raises(ValueError):
        parse_start_time("2024-01-15")
    assert parse_event_types(" login, add_user ,team_settings ") == ["login", "add_user", "team_settings"]
    with pytest.raises(ValueError):
        parse_event_types("Bad Type!")


# --- client --------------------------------------------------------------------

class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers, self.reason = status, body, headers or {}, "r"

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class Session:
    def __init__(self, responses):
        self.responses, self.calls, self.headers, self.proxies, self.trust_env = list(responses), [], {}, {}, True

    def get(self, url, params=None, auth=None, headers=None, timeout=None, verify=None):
        assert verify is True, "TLS verification must stay on"
        self.calls.append({"url": url, "params": params, "auth": auth})
        return self.responses.pop(0)


OK = {"events": [], "pagination": {"hasNextPage": False}}


def client(session, **kw):
    kw.setdefault("sleep", lambda s: None)
    kw.setdefault("min_interval_s", 0)
    return AuditLogClient("key_abc", session=session, **kw)


def test_team_request_basic_auth_and_params():
    s = Session([Resp(body=OK)])
    client(s).list_events(1000, 2000, page=2, page_size=9999, event_types=["login", "add_user"])
    call = s.calls[0]
    assert call["url"] == "https://api.cursor.com/teams/audit-logs"
    assert call["auth"] == ("key_abc", "")
    assert call["params"] == [("startTime", 1000), ("endTime", 2000), ("page", 2),
                              ("pageSize", MAX_PAGE_SIZE), ("eventTypes", "login,add_user")]
    assert s.headers["User-Agent"].startswith("TA-cursor-audit-logs/")


def test_organization_endpoint_and_team_filter():
    s = Session([Resp(body=OK), Resp(body=OK)])
    client(s, key_type="organization", team_id="42").list_events(0, 1)
    assert s.calls[0]["url"] == "https://api.cursor.com/organizations/audit-logs"
    assert ("teamId", "42") in s.calls[0]["params"]
    s2 = Session([Resp(body=OK)])
    client(s2, key_type="team", team_id="42").list_events(0, 1)  # team keys ignore teamId
    assert not any(k == "teamId" for k, _ in s2.calls[0]["params"])


def test_rejects_bad_config_and_ranges():
    for kw in ({"key_type": "user"}, {"team_id": "abc", "key_type": "organization"}):
        with pytest.raises(ValueError):
            AuditLogClient("k", **kw)
    with pytest.raises(ValueError):
        AuditLogClient("  ")
    with pytest.raises(ValueError):
        client(Session([])).list_events(0, 31 * 24 * 3600 * 1000)


def test_throttle_spaces_requests_for_20_per_minute():
    clock = [100.0]
    waits = []

    def sleep(s):
        waits.append(s)
        clock[0] += s

    s = Session([Resp(body=OK)] * 3)
    c = AuditLogClient("k", session=s, sleep=sleep, monotonic=lambda: clock[0])
    for _ in range(3):
        c.list_events(0, 1)
    assert waits == [pytest.approx(3.2), pytest.approx(3.2)]


def test_retries_429_with_retry_after_then_succeeds():
    waits = []
    s = Session([Resp(429, headers={"Retry-After": "60"}), Resp(503), Resp(body=OK)])
    client(s, sleep=waits.append).test_connection(now_ms=10_000_000)
    assert waits[0] == 60 and len(s.calls) == 3


def test_auth_errors_fail_fast_with_hint_and_no_secret():
    s = Session([Resp(401, body={"error": "Invalid API key"})])
    with pytest.raises(CursorApiError) as e:
        client(s).list_events(0, 1)
    assert e.value.status == 401 and "Invalid API key" in str(e.value) and "key_abc" not in str(e.value)
    s = Session([Resp(403, body=ValueError("not json"))])
    with pytest.raises(CursorApiError, match="Enterprise"):
        client(s).list_events(0, 1)


def test_bad_body_rejected():
    with pytest.raises(CursorApiError, match="format"):
        client(Session([Resp(body=["x"])])).list_events(0, 1)
    with pytest.raises(CursorApiError, match="JSON"):
        client(Session([Resp(body=ValueError("x"))])).list_events(0, 1)


def test_proxies():
    assert build_proxies({"proxy_enabled": "0"}) is None
    p = build_proxies({"proxy_enabled": "1", "proxy_url": "p.local", "proxy_port": "3128",
                       "proxy_username": "u@x", "proxy_password": "p:w"})
    assert p["https"] == "http://u%40x:p%3Aw@p.local:3128"
    s = Session([])
    client(s, proxies=p)
    assert s.proxies["https"] == p["https"] and s.trust_env is False


# --- package consistency ---------------------------------------------------------

def test_versions_match():
    gc = json.load(open(os.path.join(ROOT, "globalConfig.json")))["meta"]["version"]
    manifest = json.load(open(os.path.join(ROOT, "package", "app.manifest")))["info"]["id"]["version"]
    app_conf = open(os.path.join(ROOT, "package", "default", "app.conf")).read()
    conf_versions = set(re.findall(r"^version = (\S+)$", app_conf, re.M))
    assert {gc, manifest, cursor_audit.ADDON_VERSION} | conf_versions == {gc}


def test_names_and_config_match_code():
    gc = json.load(open(os.path.join(ROOT, "globalConfig.json")))
    manifest = json.load(open(os.path.join(ROOT, "package", "app.manifest")))
    app_conf = open(os.path.join(ROOT, "package", "default", "app.conf")).read()
    title = "Audit Logs Add-on for Cursor"
    assert gc["meta"]["displayName"] == manifest["info"]["title"] == title
    assert "label = {}".format(title) in app_conf
    assert gc["meta"]["name"] == cursor_audit.ADDON_NAME
    assert gc["meta"]["restRoot"].lower() == cursor_audit.CONF_PREFIX
    svc = gc["pages"]["inputs"]["services"][0]
    assert svc["name"] == "cursor_audit_logs"
    assert os.path.isfile(os.path.join(ROOT, "package", "bin", svc["name"] + ".py"))
    acct = gc["pages"]["configuration"]["tabs"][0]
    assert os.path.isfile(os.path.join(ROOT, "package", "bin", acct["restHandlerModule"] + ".py"))
    assert any(e["field"] == "api_key" and e.get("encrypted") for e in acct["entity"])
    for page in (acct["entity"], svc["entity"]):
        for e in page:
            if e["type"] in ("singleSelect", "multipleSelect"):
                assert e.get("validators"), e["field"]
    assert manifest["platformRequirements"]["splunk"]["Enterprise"] == "*"


def test_tags_reference_eventtypes():
    d = os.path.join(ROOT, "package", "default")
    eventtypes = re.findall(r"^\[(\w+)\]", open(os.path.join(d, "eventtypes.conf")).read(), re.M)
    for et in re.findall(r"^\[eventtype=(\w+)\]", open(os.path.join(d, "tags.conf")).read(), re.M):
        assert et in eventtypes
