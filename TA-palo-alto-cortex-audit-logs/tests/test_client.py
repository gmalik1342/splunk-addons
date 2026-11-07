import hashlib

import pytest
import requests

from cortex_audit.client import (
    CortexApiError,
    CortexAuditClient,
    build_proxies,
    normalize_api_url,
)
from fakes import FakeCortex, FakeResponse

MGMT = "/public_api/v1/audits/management_logs"


def make_client(session, **kw):
    kw.setdefault("auth_type", "advanced")
    return CortexAuditClient(
        "api-tenant.xdr.us.paloaltonetworks.com", "7", "secret",
        session=session, sleep=lambda s: None, min_request_interval=0, **kw
    )


@pytest.mark.parametrize("value,expected", [
    ("api-t.xdr.us.paloaltonetworks.com", "https://api-t.xdr.us.paloaltonetworks.com"),
    ("https://api-t.xdr.us.paloaltonetworks.com/", "https://api-t.xdr.us.paloaltonetworks.com"),
    ("  HTTPS://api-t.example.com:8443 ", "https://api-t.example.com:8443"),
])
def test_normalize_ok(value, expected):
    assert normalize_api_url(value) == expected


@pytest.mark.parametrize("value", [
    "", "http://api-t.example.com", "https://t.example.com",
    "https://api-t.example.com/public_api/v1", "api-t.example.com?x=1",
])
def test_normalize_rejects(value):
    with pytest.raises(ValueError):
        normalize_api_url(value)


def test_advanced_auth_signature():
    s = FakeCortex([], "AUDIT_INSERT_TIME")
    make_client(s).post(MGMT, {})
    h = s.calls[0]["headers"]
    assert h["x-xdr-auth-id"] == "7"
    assert len(h["x-xdr-nonce"]) == 64
    expected = hashlib.sha256(("secret" + h["x-xdr-nonce"] + h["x-xdr-timestamp"]).encode()).hexdigest()
    assert h["Authorization"] == expected


def test_standard_auth_sends_key():
    s = FakeCortex([], "AUDIT_INSERT_TIME")
    make_client(s, auth_type="standard").post(MGMT, {})
    h = s.calls[0]["headers"]
    assert h["Authorization"] == "secret" and "x-xdr-nonce" not in h


def test_user_agent_set():
    s = FakeCortex([], "AUDIT_INSERT_TIME")
    make_client(s)
    assert s.headers["User-Agent"].startswith("TA-palo-alto-cortex-audit-logs/")


def test_retries_429_then_succeeds():
    slept = []
    s = FakeCortex([], "AUDIT_INSERT_TIME", responses=[
        FakeResponse(429, {"reply": {}}, {"Retry-After": "3"}),
        FakeResponse(503, None),
        requests.ConnectionError("boom"),
    ])
    c = CortexAuditClient("api-t.example.com", "7", "k", session=s,
                          sleep=slept.append, min_request_interval=0)
    reply = c.post(MGMT, {})
    assert reply["total_count"] == 0
    assert slept[0] == 3.0 and len(slept) == 3


def test_retries_exhausted_raises():
    s = FakeCortex([], "AUDIT_INSERT_TIME", responses=[FakeResponse(500, None)] * 3)
    c = make_client(s, max_retries=2)
    with pytest.raises(CortexApiError) as e:
        c.post(MGMT, {})
    assert e.value.status == 500 and len(s.calls) == 3


def test_auth_error_not_retried_and_message():
    s = FakeCortex([], "AUDIT_INSERT_TIME", responses=[
        FakeResponse(401, {"reply": {"err_code": 401, "err_msg": "Public API request unauthorized"}})
    ])
    with pytest.raises(CortexApiError) as e:
        make_client(s).post(MGMT, {})
    assert e.value.status == 401 and len(s.calls) == 1
    assert "unauthorized" in str(e.value) and "secret" not in str(e.value)


def test_invalid_json_and_missing_reply():
    s = FakeCortex([], "x", responses=[FakeResponse(200, None), FakeResponse(200, {"oops": 1})])
    c = make_client(s)
    with pytest.raises(CortexApiError):
        c.post(MGMT, {})
    with pytest.raises(CortexApiError):
        c.post(MGMT, {})


def test_iter_window_paginates_and_filters():
    records = [{"AUDIT_ID": i, "AUDIT_INSERT_TIME": 1000 + i} for i in range(250)]
    s = FakeCortex(records, "AUDIT_INSERT_TIME")
    got = list(make_client(s).iter_window(MGMT, 1000, 1249))
    assert [r["AUDIT_ID"] for r in got] == list(range(250))
    bodies = [c["body"]["request_data"] for c in s.calls]
    assert [(b["search_from"], b["search_to"]) for b in bodies] == [(0, 100), (100, 200), (200, 300)]
    assert {"field": "timestamp", "operator": "gte", "value": 1000} in bodies[0]["filters"]
    assert {"field": "timestamp", "operator": "lte", "value": 1249} in bodies[0]["filters"]
    assert "sort" not in bodies[0]


def test_iter_window_exact_page_multiple_stops():
    records = [{"AUDIT_INSERT_TIME": 1} for _ in range(200)]
    s = FakeCortex(records, "AUDIT_INSERT_TIME")
    assert len(list(make_client(s).iter_window(MGMT, 0, 5))) == 200
    assert len(s.calls) == 2


def test_proxy_dict():
    assert build_proxies(None) is None
    assert build_proxies({"proxy_enabled": "0", "proxy_url": "p", "proxy_port": "1"}) is None
    p = build_proxies({"proxy_enabled": "1", "proxy_url": "proxy.local", "proxy_port": "3128",
                       "proxy_username": "u@x", "proxy_password": "p:w"})
    assert p["https"] == "http://u%40x:p%3Aw@proxy.local:3128"
    p = build_proxies({"proxy_enabled": "true", "proxy_type": "socks5", "proxy_rdns": "1",
                       "proxy_url": "s", "proxy_port": "1080"})
    assert p["https"] == "socks5h://s:1080"


def test_proxy_applied_to_session():
    s = FakeCortex([], "x")
    make_client(s, proxies={"https": "http://p:1"})
    assert s.proxies["https"] == "http://p:1" and s.trust_env is False
