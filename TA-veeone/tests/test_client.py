import json
import os
import re

import pytest
import requests

import veeone
from veeone.client import (
    SPECIALIST_STATS_PATH,
    VeeOneApiError,
    VeeOneClient,
    build_proxies,
    extract_records,
    normalize_base_url,
)

ROOT = os.path.join(os.path.dirname(__file__), "..")


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None, text=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.reason = "reason"
        self._text = text

    def json(self):
        if self._text is not None:
            return json.loads(self._text)
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}
        self.proxies = {}
        self.trust_env = True

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def client(session, **kw):
    return VeeOneClient("https://openapi-uat.veeone.io", "k3y", session=session, sleep=lambda s: None, **kw)


@pytest.mark.parametrize("value,expected", [
    ("openapi.veeone.io", "https://openapi.veeone.io"),
    ("https://openapi-uat.veeone.io/", "https://openapi-uat.veeone.io"),
    ("  HTTPS://api.veeone.com:8443 ", "https://api.veeone.com:8443"),
])
def test_normalize_ok(value, expected):
    assert normalize_base_url(value) == expected


@pytest.mark.parametrize("value", [
    "", "http://openapi.veeone.io", "https://openapi.veeone.io/api/v2", "localhost", "openapi.veeone.io?x=1",
])
def test_normalize_rejects(value):
    with pytest.raises(ValueError):
        normalize_base_url(value)


def test_request_shape():
    s = FakeSession([FakeResponse(body=[{"specialistId": 1}])])
    assert client(s).fetch_specialist_stats() == [{"specialistId": 1}]
    call = s.calls[0]
    assert call["url"] == "https://openapi-uat.veeone.io" + SPECIALIST_STATS_PATH
    assert call["headers"]["X-API-Key"] == "k3y"
    assert s.headers["User-Agent"].startswith("TA-veeone/")


def test_retries_then_succeeds():
    s = FakeSession([
        requests.ConnectionError("boom"),
        FakeResponse(503),
        FakeResponse(429, headers={"Retry-After": "2"}),
        FakeResponse(body=[]),
    ])
    assert client(s).fetch_specialist_stats() == []
    assert len(s.calls) == 4


def test_gives_up_after_max_retries():
    s = FakeSession([FakeResponse(500)] * 3)
    with pytest.raises(VeeOneApiError) as e:
        client(s, max_retries=2).fetch_specialist_stats()
    assert e.value.status == 500


def test_auth_error_not_retried():
    s = FakeSession([FakeResponse(401)])
    with pytest.raises(VeeOneApiError, match="API key"):
        client(s).fetch_specialist_stats()
    assert len(s.calls) == 1


def test_non_json_body():
    s = FakeSession([FakeResponse(text="<html>")])
    with pytest.raises(VeeOneApiError, match="JSON"):
        client(s).fetch_specialist_stats()


def test_api_key_required():
    with pytest.raises(ValueError):
        VeeOneClient("https://openapi.veeone.io", "")


@pytest.mark.parametrize("body,expected", [
    ([{"a": 1}, {"a": 2}], [{"a": 1}, {"a": 2}]),
    ({"data": [{"a": 1}]}, [{"a": 1}]),
    ({"total": 3}, [{"total": 3}]),
    ([1, 2], [{"value": 1}, {"value": 2}]),
    (None, []),
])
def test_extract_records(body, expected):
    assert extract_records(body) == expected


def test_proxies():
    assert build_proxies(None) is None
    assert build_proxies({"proxy_enabled": "0", "proxy_url": "p", "proxy_port": "1"}) is None
    p = build_proxies({"proxy_enabled": "1", "proxy_url": "proxy.local", "proxy_port": "3128",
                       "proxy_username": "u@x", "proxy_password": "p:w"})
    assert p["https"] == "http://u%40x:p%3Aw@proxy.local:3128"
    p = build_proxies({"proxy_enabled": "true", "proxy_type": "socks5", "proxy_rdns": "1",
                       "proxy_url": "s", "proxy_port": "1080"})
    assert p["http"] == "socks5h://s:1080"


def test_proxy_disables_env():
    s = FakeSession([])
    client(s, proxies={"https": "http://p:1"})
    assert s.trust_env is False and s.proxies["https"] == "http://p:1"


def test_versions_match():
    gc = json.load(open(os.path.join(ROOT, "globalConfig.json")))["meta"]["version"]
    manifest = json.load(open(os.path.join(ROOT, "package", "app.manifest")))["info"]["id"]["version"]
    app_conf = open(os.path.join(ROOT, "package", "default", "app.conf")).read()
    conf_versions = set(re.findall(r"^version = (\S+)$", app_conf, re.M))
    assert {gc, manifest, veeone.ADDON_VERSION} | conf_versions == {gc}
