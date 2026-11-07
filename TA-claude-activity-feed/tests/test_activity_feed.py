import json
import os
import re

import pytest

import claude_activity
from claude_activity.client import ANTHROPIC_VERSION, ActivityFeedClient, AnthropicApiError
from claude_activity.collector import (
    DEFAULT_LOOKBACK_S,
    collect,
    format_time,
    parse_activity_types,
    parse_start_time,
    parse_time,
)

ROOT = os.path.join(os.path.dirname(__file__), "..")
T0 = 1_800_000_000  # 2027-01-15T08:00:00Z


def act(i, t, typ="claude_chat_created"):
    return {"id": "activity_{:04d}".format(i), "created_at": format_time(t), "type": typ,
            "actor": {"type": "user_actor", "email_address": "u@example.com"}}


class FakeFeed:
    """Newest-first feed with after_id cursors; only returns activities already 'indexed'."""

    def __init__(self, activities):
        self.activities = activities  # list of (activity, indexed_at)
        self.now = T0
        self.calls = []

    def list_activities(self, gte, lt, after_id=None, limit=1000, activity_types=None):
        self.calls.append((gte, lt, after_id, limit, activity_types))
        lo, hi = parse_time(gte), parse_time(lt)
        rows = [a for a, idx in self.activities
                if idx <= self.now and lo <= parse_time(a["created_at"]) < hi
                and (not activity_types or a["type"] in activity_types)]
        rows.sort(key=lambda a: (parse_time(a["created_at"]), a["id"]), reverse=True)
        start = 0
        if after_id:
            start = [a["id"] for a in rows].index(after_id) + 1
        page = rows[start:start + limit]
        return {"data": page, "has_more": start + limit < len(rows),
                "first_id": page[0]["id"] if page else None, "last_id": page[-1]["id"] if page else None}


def run(feed, state, **kw):
    out, saved = [], []
    stats = collect(feed, state, lambda a, t: out.append((a["id"], t)), saved.append,
                    clock=lambda: feed.now, **kw)
    return (saved[-1] if saved else state), stats, out


def test_first_run_default_lookback_and_lag():
    feed = FakeFeed([(act(1, T0 - 3000), 0), (act(2, T0 - 60), 0)])  # 2nd is inside the lag
    state, stats, out = run(feed, None)
    assert [i for i, _ in out] == ["activity_0001"]
    assert out[0][1] == T0 - 3000
    assert parse_time(state["high_water"]) == T0 - 120
    assert parse_time(feed.calls[0][0]) == T0 - DEFAULT_LOOKBACK_S  # no overlap before first start


def test_start_time_and_windows_of_one_hour():
    feed = FakeFeed([(act(i, T0 - 3 * 3600 + i * 600), 0) for i in range(15)])
    state, stats, out = run(feed, None, start_time=T0 - 3 * 3600)
    assert len(out) == 15 and stats.windows == 3


def test_incremental_no_duplicates_and_late_arrival():
    early = act(1, T0 - 1000)
    late = act(2, T0 - 400)            # created inside the first window...
    feed = FakeFeed([(early, 0), (late, T0 + 200)])  # ...but indexed after it closed
    state, _, out1 = run(feed, None, start_time=T0 - 2000)
    assert [i for i, _ in out1] == ["activity_0001"]
    feed.now = T0 + 300                 # next poll; overlap re-reads the last 10 minutes
    state, stats, out2 = run(feed, state)
    assert [i for i, _ in out2] == ["activity_0002"]
    feed.now = T0 + 600
    _, stats3, out3 = run(feed, state)
    assert out3 == []                   # overlap returned activity_0002 again...
    assert stats3.duplicates == 1       # ...and it was de-duplicated, not re-emitted


def test_paging_with_cursor():
    feed = FakeFeed([(act(i, T0 - 3000 + i), 0) for i in range(25)])
    _, stats, out = run(feed, None, start_time=T0 - 3500, page_limit=10)
    assert len(out) == 25 and len({i for i, _ in out}) == 25
    assert [c[2] for c in feed.calls] == [None, "activity_0015", "activity_0005"]


def test_activity_type_filter_passed():
    feed = FakeFeed([(act(1, T0 - 3000, "sso_login_initiated"), 0), (act(2, T0 - 2000), 0)])
    _, _, out = run(feed, None, start_time=T0 - 3500, activity_types=["sso_login_initiated"])
    assert [i for i, _ in out] == ["activity_0001"] and feed.calls[0][4] == ["sso_login_initiated"]


def test_checkpoint_saved_per_window_and_recent_pruned():
    feed = FakeFeed([(act(i, T0 - 5 * 3600 + i * 60), 0) for i in range(200)])
    state, stats, out = run(feed, None, start_time=T0 - 5 * 3600)
    assert stats.windows == 5 and len(out) == 200
    assert all(v >= parse_time(state["high_water"]) - 600 - 60 for v in state["recent"].values())


def test_stops_on_max_runtime():
    feed = FakeFeed([])
    times = iter(range(0, 100000, 4000))
    stats = collect(feed, None, lambda a, t: None, lambda s: None, start_time=T0 - 10 * 3600,
                    clock=lambda: T0 + next(times) * 0, max_runtime_s=-1)
    assert stats.stopped_early and stats.windows == 0


def test_lag_never_below_60s():
    feed = FakeFeed([(act(1, T0 - 30), 0)])
    _, _, out = run(feed, None, start_time=T0 - 600, lag_s=0)
    assert out == []


def test_parsers():
    assert parse_time("2026-04-10T08:09:10Z") == parse_time("2026-04-10T10:09:10+02:00")
    assert parse_time("2026-04-10T08:09:10.123456789Z") % 1 == pytest.approx(0.123456789)
    assert parse_time("not a time") is None and parse_time(None) is None
    assert parse_start_time("") is None
    with pytest.raises(ValueError):
        parse_start_time("2026-04-10")
    assert parse_activity_types(" a_b, c ,d ") == ["a_b", "c", "d"]
    with pytest.raises(ValueError):
        parse_activity_types("Bad-Type")


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


def test_client_request():
    s = Session([Resp(body={"data": [], "has_more": False})])
    ActivityFeedClient("sk-ant-admin01-x", session=s, sleep=lambda x: None).list_activities(
        "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z", after_id="cur", limit=9999, activity_types=["a", "b"])
    url, params, headers = s.calls[0]
    assert url == "https://api.anthropic.com/v1/compliance/activities"
    assert params == [("created_at.gte", "2026-01-01T00:00:00Z"), ("created_at.lt", "2026-01-01T01:00:00Z"),
                      ("limit", 5000), ("after_id", "cur"), ("activity_types[]", "a"), ("activity_types[]", "b")]
    assert headers["x-api-key"] == "sk-ant-admin01-x" and headers["anthropic-version"] == ANTHROPIC_VERSION


def test_client_retries_429_then_errors():
    s = Session([Resp(429, headers={"retry-after": "3"}), Resp(529), Resp(body={"data": []})])
    waits = []
    ActivityFeedClient("k", session=s, sleep=waits.append).test_connection()
    assert waits[0] == 3 and len(s.calls) == 3
    s = Session([Resp(403, body={"error": {"type": "permission_error", "message": "missing scope"}},
                      headers={"request-id": "req_1"})])
    with pytest.raises(AnthropicApiError) as e:
        ActivityFeedClient("k", session=s, sleep=lambda x: None).test_connection()
    assert "read:compliance_activities" in str(e.value) and "missing scope" in str(e.value) and "req_1" in str(e.value)


def test_client_rejects_bad_body_and_key():
    with pytest.raises(ValueError):
        ActivityFeedClient("  ")
    s = Session([Resp(body=["x"])])
    with pytest.raises(AnthropicApiError, match="format"):
        ActivityFeedClient("k", session=s).list_activities("a", "b")


def test_versions_match():
    gc = json.load(open(os.path.join(ROOT, "globalConfig.json")))["meta"]["version"]
    manifest = json.load(open(os.path.join(ROOT, "package", "app.manifest")))["info"]["id"]["version"]
    app_conf = open(os.path.join(ROOT, "package", "default", "app.conf")).read()
    conf_versions = set(re.findall(r"^version = (\S+)$", app_conf, re.M))
    assert {gc, manifest, claude_activity.ADDON_VERSION} | conf_versions == {gc}
