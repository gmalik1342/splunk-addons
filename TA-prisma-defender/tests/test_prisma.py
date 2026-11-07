import base64
import json
import os
import re

import pytest

import prisma_compute
from prisma_compute.client import (
    MAX_PAGE_SIZE,
    PrismaApiError,
    PrismaClient,
    normalize_api_version,
    normalize_console_url,
)
from prisma_compute.records import defender_record, defenders_summary_record, registry_records

ROOT = os.path.join(os.path.dirname(__file__), "..")


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers, self.reason = status, body, headers or {}, "r"

    def json(self):
        return self._body


class Session:
    """Serves /defenders with limit/offset from a list; other endpoints from a dict."""

    def __init__(self, defenders=None, other=None, responses=None):
        self.defenders = defenders or []
        self.other = other or {}
        self.responses = list(responses or [])
        self.calls = []
        self.headers, self.proxies, self.trust_env, self.auth = {}, {}, True, None

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        if self.responses:
            return self.responses.pop(0)
        if url.endswith("/defenders"):
            o, n = params["offset"], params["limit"]
            return Resp(body=self.defenders[o:o + n])
        for suffix, body in self.other.items():
            if url.endswith(suffix):
                return Resp(body=body)
        return Resp(404)


def client(session, **kw):
    return PrismaClient("https://us-east1.cloud.twistlock.com/us-1-123", "AK", "SK",
                        api_version="v34.02", session=session, sleep=lambda s: None, **kw)


@pytest.mark.parametrize("value,expected", [
    ("https://us-east1.cloud.twistlock.com/us-1-123/", "https://us-east1.cloud.twistlock.com/us-1-123"),
    ("console.example.com:8083", "https://console.example.com:8083"),
    ("https://console.example.com:8083/api/v1/defenders", "https://console.example.com:8083"),
    ("https://twistlock:8083", "https://twistlock:8083"),
])
def test_normalize_console_ok(value, expected):
    assert normalize_console_url(value) == expected


@pytest.mark.parametrize("value", ["", "http://console:8083", "https://c.example.com/x?y=1", "https://c ex.com"])
def test_normalize_console_rejects(value):
    with pytest.raises(ValueError):
        normalize_console_url(value)


def test_api_version():
    assert normalize_api_version(None) == "v1" and normalize_api_version(" v34.02 ") == "v34.02"
    with pytest.raises(ValueError):
        normalize_api_version("34.02")


def test_auth_tls_and_url():
    s = Session(other={"/defenders/summary": []})
    c = client(s)
    c.defenders_summary()
    assert s.calls[0][0] == "https://us-east1.cloud.twistlock.com/us-1-123/api/v34.02/defenders/summary"
    assert (s.auth.username, s.auth.password) == ("AK", "SK")
    req = type("R", (), {"headers": {}})()
    s.auth(req)
    assert req.headers["Authorization"] == "Basic " + base64.b64encode(b"AK:SK").decode()
    assert not hasattr(s, "verify") or s.verify is not False


def test_defenders_all_pages_and_disconnected():
    defenders = [{"hostname": "h{}".format(i), "connected": i % 2 == 0} for i in range(120)]
    s = Session(defenders=defenders)
    got = list(client(s).iter_defenders())
    assert len(got) == 120
    offsets = [c[1]["offset"] for c in s.calls]
    assert offsets == [0, 50, 100] and all(c[1]["limit"] == MAX_PAGE_SIZE for c in s.calls)
    assert "connected" not in s.calls[0][1]
    assert "manageDefenders" in s.calls[0][2]["x-prisma-cloud-target-env"]


def test_page_size_capped_at_50():
    s = Session(defenders=[{"hostname": "x"}] * 3)
    list(client(s).iter_defenders(page_size=100))
    assert s.calls[0][1]["limit"] == 50


def test_null_body_is_empty_list():
    s = Session(responses=[Resp(body=None)])
    assert client(s).registry_progress() == []


def test_errors():
    s = Session(responses=[Resp(503), Resp(429, headers={"Retry-After": "1"}), Resp(body=[])])
    assert client(s).defenders_summary() == [] and len(s.calls) == 3
    with pytest.raises(PrismaApiError, match="access key"):
        client(Session(responses=[Resp(401)])).defenders_summary()
    with pytest.raises(PrismaApiError, match="format"):
        client(Session(responses=[Resp(body={"x": 1})])).defenders_summary()


def test_defender_record():
    r = defender_record({
        "hostname": "node1", "connected": False, "lastModified": "2026-01-02T03:04:05.123456789Z",
        "cloudMetadata": {"provider": "aws", "accountID": "1", "region": "us-east-1"},
        "status": {"runtime": {"enabled": True}, "network": {"enabled": True, "err": "boom"}},
        "collections": ["All"],
    })
    assert r["record_type"] == "defender" and r["connected"] is False
    assert r["features_enabled"] == "Runtime, Network" and r["errors"] == "network: boom"
    assert r["cloud_provider"] == "aws" and r["collections"] == "All"
    assert r["last_modified"]  # parsed or raw, never raises


def test_defenders_summary_record():
    r = defenders_summary_record([
        {"category": "host", "connected": 3, "deployed": 4, "licensed": 4},
        {"category": "container", "connected": 10, "deployed": 10, "licensed": 10},
    ])
    assert r["defenders_summary"]["connected"] == {"host": 3, "container": 10}
    assert defenders_summary_record([]) is None


def test_registry_records_all_and_stats():
    data = [
        {"discovery": {"id": "r{}".format(i), "total": 10, "scanned": 5,
                       "error": "timeout, scanned by defender: d1" if i == 0 else ""},
         "imageScan": {"total": 3, "scanned": None}, "isScanOngoing": True}
        for i in range(3)
    ]
    out = registry_records(data)
    assert [r["record_type"] for r in out] == ["registry_scan_progress"] * 3 + ["registry_scan_statistics"]
    assert out[0]["error_message"] == "timeout" and out[0]["defender"] == "d1"
    stats = out[-1]["statistics"]
    assert stats["total_discovery_repositories"] == 30 and stats["total_images_scanned"] == 0
    assert stats["records_with_errors"] == 1 and out[-1]["total_records_processed"] == 3
    assert registry_records([]) == []


def test_versions_match():
    gc = json.load(open(os.path.join(ROOT, "globalConfig.json")))["meta"]["version"]
    manifest = json.load(open(os.path.join(ROOT, "package", "app.manifest")))["info"]["id"]["version"]
    app_conf = open(os.path.join(ROOT, "package", "default", "app.conf")).read()
    conf_versions = set(re.findall(r"^version = (\S+)$", app_conf, re.M))
    assert {gc, manifest, prisma_compute.ADDON_VERSION} | conf_versions == {gc}
