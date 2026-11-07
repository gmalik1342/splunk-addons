import json
import os
import re

import pytest

import prisma_compute
from prisma_compute.client import MAX_PAGE_SIZE, PrismaApiError, PrismaClient, normalize_console_url

ROOT = os.path.join(os.path.dirname(__file__), "..")

CSV = "﻿Account ID,Region,Service,Defended\r\n111,us-east-1,EC2,true\r\n222,eu-west-1,EKS,false\r\n"


class Resp:
    def __init__(self, status=200, body=None, text=None, headers=None):
        self.status_code, self._body, self.headers, self.reason = status, body, headers or {}, "r"
        self.text, self.encoding = text, None

    def json(self):
        return self._body


class Session:
    def __init__(self, results=None, csv_text=CSV, responses=None):
        self.results = results or []
        self.csv_text = csv_text
        self.responses = list(responses or [])
        self.calls = []
        self.headers, self.proxies, self.trust_env, self.auth = {}, {}, True, None

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        if self.responses:
            return self.responses.pop(0)
        if url.endswith("/cloud/discovery/download"):
            return Resp(text=self.csv_text)
        if url.endswith("/cloud/discovery"):
            o, n = params["offset"], params["limit"]
            return Resp(body=self.results[o:o + n])
        return Resp(404)


def client(session):
    return PrismaClient("https://us-east1.cloud.twistlock.com/us-1-123", "AK", "SK",
                        api_version="v34.02", session=session, sleep=lambda s: None)


def test_download_csv_rows():
    s = Session()
    rows = list(client(s).iter_discovery_download())
    assert rows == [
        {"Account ID": "111", "Region": "us-east-1", "Service": "EC2", "Defended": "true"},
        {"Account ID": "222", "Region": "eu-west-1", "Service": "EKS", "Defended": "false"},
    ]
    url, _, headers = s.calls[0]
    assert url == "https://us-east1.cloud.twistlock.com/us-1-123/api/v34.02/cloud/discovery/download"
    assert headers["Accept"] == "text/csv" and "monitorCloud" in headers["x-prisma-cloud-target-env"]
    assert (s.auth.username, s.auth.password) == ("AK", "SK")


def test_empty_download():
    assert list(client(Session(csv_text="")).iter_discovery_download()) == []


def test_scan_results_all_pages():
    results = [{"accountID": str(i), "region": "r", "serviceType": "aws-ec2"} for i in range(101)]
    s = Session(results=results)
    got = list(client(s).iter_discovery_results())
    assert len(got) == 101
    assert [c[1]["offset"] for c in s.calls] == [0, 50, 100]
    assert all(c[1]["limit"] == MAX_PAGE_SIZE for c in s.calls)
    assert "monitorCloud" in s.calls[0][2]["x-prisma-cloud-target-env"]


def test_scan_results_null_body():
    assert list(client(Session(responses=[Resp(body=None)])).iter_discovery_results()) == []


def test_errors_raised_not_swallowed():
    with pytest.raises(PrismaApiError, match="Monitor Cloud"):
        list(client(Session(responses=[Resp(403)])).iter_discovery_results())
    with pytest.raises(PrismaApiError, match="access key"):
        list(client(Session(responses=[Resp(401)])).iter_discovery_download())
    s = Session(responses=[Resp(502), Resp(text="a,b\r\n1,2\r\n")])
    assert list(client(s).iter_discovery_download()) == [{"a": "1", "b": "2"}]


def test_console_url():
    assert normalize_console_url("https://c.example.com:8083/api/v34.02/cloud/discovery") == "https://c.example.com:8083"
    with pytest.raises(ValueError):
        normalize_console_url("http://c.example.com")


def test_versions_match():
    gc = json.load(open(os.path.join(ROOT, "globalConfig.json")))["meta"]["version"]
    manifest = json.load(open(os.path.join(ROOT, "package", "app.manifest")))["info"]["id"]["version"]
    app_conf = open(os.path.join(ROOT, "package", "default", "app.conf")).read()
    conf_versions = set(re.findall(r"^version = (\S+)$", app_conf, re.M))
    assert {gc, manifest, prisma_compute.ADDON_VERSION} | conf_versions == {gc}
