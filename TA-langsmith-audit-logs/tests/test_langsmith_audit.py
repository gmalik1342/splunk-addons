import base64
import json
import os
import re

import pytest

import langsmith_audit
from langsmith_audit.client import (
    MAX_LIMIT,
    AuditLogClient,
    LangSmithApiError,
    build_proxies,
    format_iso_ms,
    resolve_base_url,
)
from langsmith_audit.collector import (
    DEFAULT_LOOKBACK_S,
    collect,
    event_id,
    event_time,
    parse_operations,
    parse_start_time,
    parse_time,
)

ROOT = os.path.join(os.path.dirname(__file__), "..")
T0 = 1_800_000_000  # 2027-01-15T08:00:00Z
ORG = "11111111-2222-3333-4444-555555555555"
WS = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def item(i, t, op="create_api_key", status="Success"):
    """OCSF API Activity (6003) item, time in epoch ms."""
    return {
        "class_uid": 6003, "class_name": "API Activity", "activity_name": "Create",
        "status": status, "time": int(t * 1000),
        "metadata": {"uid": "audit-{:05d}".format(i), "product": {"name": "LangSmith", "vendor_name": "LangChain"}},
        "api": {"operation": op},
        "http_request": {"http_method": "POST", "url": {"path": "/api/v1/api-key"}},
        "http_response": {"code": 200},
        "actor": {"user": {"uid": "user-1", "credential_uid": "key-1"}},
        "src_endpoint": {"ip": "198.51.100.4"},
        "resources": [{"uid": "res-{}".format(i)}],
        "unmapped": {"original_audit_log": {"operation_name": op, "organization_id": ORG,
                                            "workspace_id": WS, "request_time": "x"}},
    }


class FakeLangSmith:
    """Inclusive [start_time, end_time], cursor = base64 offset, limit ≤ 100.

    Items become visible once 'recorded' (late recording simulates lag).
    """

    def __init__(self, items):
        self.items = items  # list of (item, recorded_at)
        self.now = T0
        self.calls = []

    def list_audit_logs(self, start_ms, end_ms, cursor=None, limit=100, operations=None):
        self.calls.append((start_ms, end_ms, cursor, limit, operations))
        rows = [it for it, rec in self.items
                if rec <= self.now and start_ms <= it["time"] <= end_ms
                and (not operations or it["api"]["operation"] in operations)]
        rows.sort(key=lambda it: (it["time"], it["metadata"]["uid"]), reverse=True)  # newest first
        offset = json.loads(base64.b64decode(cursor))["o"] if cursor else 0
        page = rows[offset:offset + limit]
        nxt = offset + limit
        return {"items": page,
                "cursor": base64.b64encode(json.dumps({"o": nxt}).encode()).decode() if nxt < len(rows) else None}


def run(api, state, **kw):
    out, saved = [], []
    stats = collect(api, state, lambda it, t: out.append((event_id(it), t)), saved.append,
                    clock=lambda: api.now, **kw)
    return (saved[-1] if saved else state), stats, out


# --- collector -----------------------------------------------------------------

def test_first_run_lookback_lag_and_event_time():
    api = FakeLangSmith([(item(1, T0 - 3000), 0), (item(2, T0 - 100), 0)])  # 2nd inside the 300 s lag
    state, _, out = run(api, None)
    assert [i for i, _ in out] == ["audit-00001"] and out[0][1] == T0 - 3000
    assert state["high_water_ms"] == (T0 - 300) * 1000
    assert api.calls[0][0] == (T0 - DEFAULT_LOOKBACK_S) * 1000


def test_six_hour_windows_and_checkpoint_per_window():
    api = FakeLangSmith([(item(i, T0 - 20 * 3600 + i * 600), 0) for i in range(100)])
    saved = []
    stats = collect(api, None, lambda it, t: None, saved.append, start_time=T0 - 20 * 3600,
                    clock=lambda: api.now)
    assert stats.windows == 4 and stats.events == 100
    assert [s["high_water_ms"] for s in saved] == sorted(s["high_water_ms"] for s in saved)


def test_inclusive_edges_never_duplicate():
    edge = T0 - 3600
    api = FakeLangSmith([(item(1, edge), 0), (item(2, edge - 10), 0), (item(3, edge + 10), 0)])
    state, _, out1 = run(api, None, start_time=edge - 1000, window_s=1000)
    _, _, out2 = run(api, state)
    ids = [i for i, _ in out1 + out2]
    assert sorted(ids) == ["audit-00001", "audit-00002", "audit-00003"] and len(ids) == len(set(ids))


def test_late_recorded_event_picked_up_once():
    api = FakeLangSmith([(item(1, T0 - 1000), 0), (item(2, T0 - 400), T0 + 100)])
    state, _, out1 = run(api, None, start_time=T0 - 2000)
    assert [i for i, _ in out1] == ["audit-00001"]
    api.now = T0 + 300
    state, _, out2 = run(api, state)
    assert [i for i, _ in out2] == ["audit-00002"]
    api.now = T0 + 600
    _, stats3, out3 = run(api, state)
    assert out3 == [] and stats3.duplicates >= 1


def test_cursor_pagination():
    api = FakeLangSmith([(item(i, T0 - 3000 + i), 0) for i in range(23)])
    _, stats, out = run(api, None, start_time=T0 - 3500, page_limit=10)
    assert len(out) == 23 and len({i for i, _ in out}) == 23 and stats.pages == 3
    assert api.calls[0][2] is None and api.calls[1][2] and api.calls[2][2]


def test_repeated_cursor_stops_window():
    class Stuck:
        calls = 0

        def list_audit_logs(self, *a, **k):
            Stuck.calls += 1
            return {"items": [item(Stuck.calls, T0 - 3000)], "cursor": "same"}

    stats = collect(Stuck(), None, lambda it, t: None, lambda s: None, start_time=T0 - 3500,
                    clock=lambda: T0)
    assert Stuck.calls == 2 and stats.windows == 1


def test_operation_filter_passed():
    api = FakeLangSmith([(item(1, T0 - 3000, "login"), 0), (item(2, T0 - 2000), 0)])
    _, _, out = run(api, None, start_time=T0 - 3500, operations=["login"])
    assert [i for i, _ in out] == ["audit-00001"] and api.calls[0][4] == ["login"]


def test_recent_ids_pruned_to_overlap():
    api = FakeLangSmith([(item(i, T0 - 5 * 3600 + i * 60), 0) for i in range(295)])
    state, _, out = run(api, None, start_time=T0 - 5 * 3600)
    assert len(out) == 295
    hw = state["high_water_ms"] / 1000
    assert state["recent"] and all(v >= hw - 600 - 60 for v in state["recent"].values())


def test_stops_on_max_runtime_and_lag_floor():
    stats = collect(FakeLangSmith([]), None, lambda it, t: None, lambda s: None,
                    start_time=T0 - 10 * 3600, clock=lambda: T0, max_runtime_s=-1)
    assert stats.stopped_early and stats.windows == 0
    api = FakeLangSmith([(item(1, T0 - 30), 0)])
    _, _, out = run(api, None, start_time=T0 - 600, lag_s=0)
    assert out == []


def test_event_time_units_and_fallbacks():
    assert event_time({"time": 1_705_321_800_250}) == pytest.approx(1_705_321_800.25)   # ms (OCSF)
    assert event_time({"time": 1_705_321_800}) == 1_705_321_800.0                       # s
    assert event_time({"time": 1_705_321_800_250_000}) == pytest.approx(1_705_321_800.25)  # µs
    assert event_time({"unmapped": {"original_audit_log": {"request_time": "2024-01-15T12:30:00.5"}}}) \
        == parse_time("2024-01-15T12:30:00.5Z")
    assert event_time({"time": True}) is None and event_time({}) is None


def test_event_id_fallbacks():
    assert event_id({"metadata": {"uid": "u1"}}) == "u1"
    assert event_id({"unmapped": {"original_audit_log": {"id": 7}}}) == "7"
    a, b = event_id({"x": 1, "y": 2}), event_id({"y": 2, "x": 1})
    assert a == b and a.startswith("sha256:")


def test_parsers():
    assert parse_start_time("") is None
    assert parse_start_time("2026-11-01T00:00:00Z") == parse_time("2026-11-01T00:00:00Z")
    with pytest.raises(ValueError):
        parse_start_time("2026-11-01")
    assert parse_operations(" login, create_api_key ,update_role ") == ["login", "create_api_key", "update_role"]
    with pytest.raises(ValueError):
        parse_operations("Bad-Op")
    assert format_iso_ms(1_705_321_800_005) == "2024-01-15T12:30:00.005Z"


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

    def get(self, url, params=None, headers=None, timeout=None, verify=None):
        assert verify is True, "TLS verification must stay on"
        self.calls.append({"url": url, "params": params, "headers": headers})
        return self.responses.pop(0)


OK = {"items": [], "cursor": None}


def client(session, **kw):
    kw.setdefault("sleep", lambda s: None)
    kw.setdefault("min_interval_s", 0)
    return AuditLogClient("lsv2_sk_secret", ORG, session=session, **kw)


def test_request_headers_and_params():
    s = Session([Resp(body=OK)])
    client(s, workspace_id=WS).list_audit_logs(1_705_321_800_000, 1_705_325_400_999, cursor="abc",
                                               limit=999, operations=["login", "update_role"])
    call = s.calls[0]
    assert call["url"] == "https://api.smith.langchain.com/api/v1/audit-logs"
    assert call["headers"]["X-API-Key"] == "lsv2_sk_secret" and call["headers"]["X-Organization-Id"] == ORG
    assert call["params"] == [("start_time", "2024-01-15T12:30:00.000Z"), ("end_time", "2024-01-15T13:30:00.999Z"),
                              ("limit", MAX_LIMIT), ("cursor", "abc"), ("workspace_id", WS),
                              ("operations", "login"), ("operations", "update_role")]
    assert s.headers["User-Agent"].startswith("TA-langsmith-audit-logs/")


def test_regions_and_self_hosted():
    assert resolve_base_url("eu") == "https://eu.api.smith.langchain.com"
    assert resolve_base_url("apac") == "https://apac.api.smith.langchain.com"
    assert resolve_base_url("aws_us") == "https://aws.api.smith.langchain.com"
    assert resolve_base_url(None) == "https://api.smith.langchain.com"
    assert resolve_base_url("custom", "https://ls.example.com:8443/") == "https://ls.example.com:8443"
    for bad in ("http://ls.example.com", "https://ls.example.com/api", "ls.example.com", ""):
        with pytest.raises(ValueError):
            resolve_base_url("custom", bad)
    with pytest.raises(ValueError):
        resolve_base_url("mars")
    s = Session([Resp(body=OK)])
    client(s, base_url=resolve_base_url("custom", "https://ls.example.com")).list_audit_logs(0, 1)
    assert s.calls[0]["url"] == "https://ls.example.com/api/v1/audit-logs"


def test_rejects_bad_config():
    with pytest.raises(ValueError):
        AuditLogClient("k", "not-a-uuid")
    with pytest.raises(ValueError):
        AuditLogClient(" ", ORG)
    with pytest.raises(ValueError):
        AuditLogClient("k", ORG, workspace_id="nope")
    with pytest.raises(ValueError):
        client(Session([])).list_audit_logs(10, 5)


def test_retries_429_then_succeeds_and_paces():
    waits = []
    s = Session([Resp(429, headers={"Retry-After": "7"}), Resp(502), Resp(body=OK)])
    client(s, sleep=waits.append).test_connection(now_ms=10_000_000)
    assert waits[0] == 7 and len(s.calls) == 3
    clock = [0.0]

    def sleep(x):
        waits.append(x)
        clock[0] += x

    waits.clear()
    s = Session([Resp(body=OK)] * 2)
    c = AuditLogClient("k", ORG, session=s, sleep=sleep, monotonic=lambda: clock[0], min_interval_s=0.25)
    c.list_audit_logs(0, 1)
    c.list_audit_logs(0, 1)
    assert waits == [pytest.approx(0.25)]


def test_errors_fail_fast_with_hint_and_no_secret():
    s = Session([Resp(403, body={"detail": "Forbidden: audit logs not enabled"})])
    with pytest.raises(LangSmithApiError) as e:
        client(s).list_audit_logs(0, 1)
    msg = str(e.value)
    assert e.value.status == 403 and "Enterprise" in msg and "not enabled" in msg and "lsv2_sk_secret" not in msg
    s = Session([Resp(422, body=ValueError("x"))])
    with pytest.raises(LangSmithApiError, match="parameters"):
        client(s).list_audit_logs(0, 1)


def test_bad_body_rejected():
    with pytest.raises(LangSmithApiError, match="format"):
        client(Session([Resp(body=["x"])])).list_audit_logs(0, 1)
    with pytest.raises(LangSmithApiError, match="JSON"):
        client(Session([Resp(body=ValueError("x"))])).list_audit_logs(0, 1)


def test_proxies():
    p = build_proxies({"proxy_enabled": "1", "proxy_type": "socks5", "proxy_rdns": "1",
                       "proxy_url": "s.local", "proxy_port": "1080"})
    assert p["https"] == "socks5h://s.local:1080"
    s = Session([])
    client(s, proxies=p)
    assert s.proxies["https"] == p["https"] and s.trust_env is False


# --- package consistency ---------------------------------------------------------

def test_versions_match():
    gc = json.load(open(os.path.join(ROOT, "globalConfig.json")))["meta"]["version"]
    manifest = json.load(open(os.path.join(ROOT, "package", "app.manifest")))["info"]["id"]["version"]
    app_conf = open(os.path.join(ROOT, "package", "default", "app.conf")).read()
    conf_versions = set(re.findall(r"^version = (\S+)$", app_conf, re.M))
    assert {gc, manifest, langsmith_audit.ADDON_VERSION} | conf_versions == {gc}


def test_names_and_config_match_code():
    gc = json.load(open(os.path.join(ROOT, "globalConfig.json")))
    manifest = json.load(open(os.path.join(ROOT, "package", "app.manifest")))
    app_conf = open(os.path.join(ROOT, "package", "default", "app.conf")).read()
    title = "Audit Logs Add-on for LangSmith"
    assert gc["meta"]["displayName"] == manifest["info"]["title"] == title
    assert "label = {}".format(title) in app_conf
    assert gc["meta"]["name"] == langsmith_audit.ADDON_NAME
    assert gc["meta"]["restRoot"].lower() == langsmith_audit.CONF_PREFIX
    svc = gc["pages"]["inputs"]["services"][0]
    assert svc["name"] == "langsmith_audit_logs"
    assert os.path.isfile(os.path.join(ROOT, "package", "bin", svc["name"] + ".py"))
    acct = gc["pages"]["configuration"]["tabs"][0]
    assert os.path.isfile(os.path.join(ROOT, "package", "bin", acct["restHandlerModule"] + ".py"))
    assert any(e["field"] == "api_key" and e.get("encrypted") for e in acct["entity"])
    regions = [o["value"] for e in acct["entity"] if e["field"] == "region"
               for o in e["options"]["autoCompleteFields"]]
    assert set(regions) == {"us", "eu", "apac", "aws_us", "custom"}
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
