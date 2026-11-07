import json
import os
import re

import pytest

import cloud_secure
from cloud_secure.client import ALERTS_PATH, CloudSecureApiError, CloudSecureClient, normalize_base_url
from cloud_secure.collector import STATE_RETENTION_MS, collect

ROOT = os.path.join(os.path.dirname(__file__), "..")
NOW = 1_800_000_000_000
DAY = 24 * 3600 * 1000


def alert(i, ts=None, status="New"):
    return {"id": "a{}".format(i), "alertTimestamp": ts or NOW - i * 1000, "status": status,
            "severity": "critical", "alertType": "Ransomware Attack"}


class FakeApi:
    """Serves alerts with limit/offset; optionally ignores offset."""

    def __init__(self, alerts, ignore_offset=False, count_is_total=True):
        self.alerts = alerts
        self.ignore_offset = ignore_offset
        self.count_is_total = count_is_total
        self.calls = []

    def get_alerts(self, limit, offset, time_range):
        self.calls.append((limit, offset, time_range))
        start = 0 if self.ignore_offset else offset
        page = self.alerts[start:start + limit]
        count = len(self.alerts) if self.count_is_total else len(page)
        return {"count": count, "limit": limit, "offset": offset, "results": page}


def run(api, state=None, **kw):
    out = []
    state, stats = collect(api, state, lambda a, t: out.append((a.get("id"), t)), now_ms=NOW, **kw)
    return state, stats, out


def test_first_run_emits_all_with_alert_time():
    state, stats, out = run(FakeApi([alert(1), alert(2)]))
    assert [i for i, _ in out] == ["a1", "a2"]
    assert out[0][1] == (NOW - 1000) / 1000.0
    assert stats.new == 2 and set(state["alerts"]) == {"a1", "a2"}


def test_second_run_only_new_and_changed():
    api = FakeApi([alert(1), alert(2)])
    state, _, _ = run(api)
    api.alerts = [alert(1, status="Resolved"), alert(2), alert(3)]
    state, stats, out = run(api, state)
    assert sorted(i for i, _ in out) == ["a1", "a3"]
    assert stats.new == 1 and stats.updated == 1


def test_unchanged_emits_nothing():
    api = FakeApi([alert(1)])
    state, _, _ = run(api)
    _, stats, out = run(api, state)
    assert out == [] and stats.seen == 1


@pytest.mark.parametrize("count_is_total", [True, False])
def test_paging(count_is_total):
    api = FakeApi([alert(i) for i in range(25)], count_is_total=count_is_total)
    _, stats, out = run(api, page_size=10)
    assert len(out) == 25 and [c[1] for c in api.calls] == [0, 10, 20]


def test_exact_multiple_of_page_size():
    api = FakeApi([alert(i) for i in range(20)], count_is_total=False)
    _, stats, out = run(api, page_size=10)
    assert len(out) == 20 and stats.stopped_reason == "empty_page"


def test_offset_ignored_stops():
    api = FakeApi([alert(i) for i in range(10)], ignore_offset=True)
    _, stats, out = run(api, page_size=10)
    assert len(out) == 10 and stats.stopped_reason == "offset_ignored" and len(api.calls) == 2


def test_max_pages():
    api = FakeApi([alert(i) for i in range(50)])
    _, stats, out = run(api, page_size=10, max_pages=2)
    assert len(out) == 20 and stats.stopped_reason == "max_pages"


def test_prunes_old_state():
    old = {"version": 1, "alerts": {"gone": [NOW - STATE_RETENTION_MS - DAY, "x"], "kept": [NOW - DAY, "y"]}}
    state, _, _ = run(FakeApi([]), old)
    assert set(state["alerts"]) == {"kept"}


def test_alert_without_id_uses_content_hash():
    a = {"alertTimestamp": NOW, "status": "New"}
    api = FakeApi([a])
    state, _, out = run(api)
    _, _, out2 = run(api, state)
    assert len(out) == 1 and out2 == []


# --- client --------------------------------------------------------------------

class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers, self.reason = status, body, headers or {}, "r"

    def json(self):
        return self._body


class Session:
    def __init__(self, responses):
        self.responses, self.calls, self.headers, self.proxies, self.trust_env = list(responses), [], {}, {}, True

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return self.responses.pop(0)


def test_client_request_shape():
    s = Session([Resp(body={"count": 0, "results": []})])
    c = CloudSecureClient("xyz.c01.cloudinsights.netapp.com", "tok", session=s, sleep=lambda x: None)
    c.get_alerts(limit=1000, offset=2000)
    url, params, headers = s.calls[0]
    assert url == "https://xyz.c01.cloudinsights.netapp.com" + ALERTS_PATH
    assert params == {"limit": 1000, "offset": 2000, "timeRange": "ONE_WEEK", "sort": "alertTimestamp"}
    assert headers["X-CloudInsights-ApiKey"] == "tok"


def test_client_retries_and_errors():
    s = Session([Resp(503), Resp(429, headers={"Retry-After": "1"}), Resp(body={"results": []})])
    CloudSecureClient("https://x.cloudinsights.netapp.com", "t", session=s, sleep=lambda x: None).get_alerts(1, 0)
    assert len(s.calls) == 3
    s = Session([Resp(401)])
    with pytest.raises(CloudSecureApiError, match="token"):
        CloudSecureClient("https://x.cloudinsights.netapp.com", "t", session=s, sleep=lambda x: None).get_alerts(1, 0)
    s = Session([Resp(body=["not", "a", "dict"])])
    with pytest.raises(CloudSecureApiError, match="format"):
        CloudSecureClient("https://x.cloudinsights.netapp.com", "t", session=s, sleep=lambda x: None).get_alerts(1, 0)


@pytest.mark.parametrize("value,expected", [
    ("xyz.c01.cloudinsights.netapp.com", "https://xyz.c01.cloudinsights.netapp.com"),
    ("https://xyz.c01.cloudinsights.netapp.com/", "https://xyz.c01.cloudinsights.netapp.com"),
    ("https://xyz.ab12.cloudinsights.netapp.com/rest/v1/cloudsecure/alerts", "https://xyz.ab12.cloudinsights.netapp.com"),
])
def test_normalize_ok(value, expected):
    assert normalize_base_url(value) == expected


@pytest.mark.parametrize("value", ["", "http://x.cloudinsights.netapp.com", "https://x.netapp.com/web/ui", "localhost"])
def test_normalize_rejects(value):
    with pytest.raises(ValueError):
        normalize_base_url(value)


def test_versions_match():
    gc = json.load(open(os.path.join(ROOT, "globalConfig.json")))["meta"]["version"]
    manifest = json.load(open(os.path.join(ROOT, "package", "app.manifest")))["info"]["id"]["version"]
    app_conf = open(os.path.join(ROOT, "package", "default", "app.conf")).read()
    conf_versions = set(re.findall(r"^version = (\S+)$", app_conf, re.M))
    assert {gc, manifest, cloud_secure.ADDON_VERSION} | conf_versions == {gc}
