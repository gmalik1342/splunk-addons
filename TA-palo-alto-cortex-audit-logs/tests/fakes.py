"""Test doubles: a fake Cortex API session and an in-memory checkpoint store."""

import json

import requests


class FakeResponse:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeCortex(requests.Session):
    """Serves records filtered by timestamp window with offset pagination."""

    def __init__(self, records, time_field, responses=None):
        super().__init__()
        self.records = records
        self.time_field = time_field
        self.calls = []
        self.queued = list(responses or [])  # optional scripted responses first

    def post(self, url, json=None, headers=None, timeout=None, verify=None):  # noqa: A002
        assert verify is True, "TLS verification must stay on"
        self.calls.append({"url": url, "body": json, "headers": headers})
        if self.queued:
            item = self.queued.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        rd = json["request_data"]
        lo = hi = None
        cats = None
        for f in rd.get("filters", []):
            if f["field"] == "timestamp" and f["operator"] == "gte":
                lo = f["value"]
            elif f["field"] == "timestamp" and f["operator"] == "lte":
                hi = f["value"]
            elif f["field"] == "category":
                cats = set(f["value"])
        rows = [
            r for r in self.records
            if (lo is None or r[self.time_field] >= lo)
            and (hi is None or r[self.time_field] <= hi)
            and (cats is None or r.get("CATEGORY") in cats)
        ]
        page = rows[rd.get("search_from", 0):rd.get("search_to", 100)]
        return FakeResponse(
            200, {"reply": {"total_count": len(rows), "result_count": len(page), "data": page}}
        )


class MemoryCheckpoints:
    def __init__(self):
        self.data = {}
        self.writes = []

    def get(self, key):
        return self.data.get(key)

    def update(self, key, state):
        self.data[key] = dict(state)
        self.writes.append((key, dict(state)))
