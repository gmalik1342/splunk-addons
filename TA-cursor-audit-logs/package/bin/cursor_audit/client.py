"""HTTP client for the Cursor Admin API audit log endpoints.

* Team API key:          GET https://api.cursor.com/teams/audit-logs
* Organization API key:  GET https://api.cursor.com/organizations/audit-logs
  (scope auditlogs:read or admin:*; optional teamId to limit to one team)

Basic auth with the key as the username and an empty password. Results are
oldest first, ``page`` is 1-indexed, ``pageSize`` is at most 500 and one
request may span at most 30 days. The audit log endpoints allow 20 requests
per minute per team, so requests are spaced out and 429s are retried
(honouring ``Retry-After``). TLS is always verified.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

from . import USER_AGENT

API_BASE = "https://api.cursor.com"
PATHS = {
    "team": "/teams/audit-logs",
    "organization": "/organizations/audit-logs",
}
MAX_PAGE_SIZE = 500
MAX_RANGE_MS = 30 * 24 * 3600 * 1000
# 20 requests/minute/team: one request every 3 s, plus a little headroom.
DEFAULT_MIN_INTERVAL_S = 3.2
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

_ERROR_HINTS = {
    400: "Bad request; check the start time and event type filter.",
    401: "Authentication failed; check the API key and that the key type (Team or Organization) is correct.",
    403: "The key cannot read audit logs. Audit logs need a Cursor Enterprise plan; an Organization "
         "key needs the auditlogs:read (or admin:*) scope.",
    404: "Endpoint not found; check the key type (Team or Organization).",
}


class CursorApiError(Exception):
    """Raised when the Cursor API returns an error that should not be retried."""

    def __init__(self, status: int, message: str):
        super().__init__("HTTP {}: {}".format(status, message))
        self.status = status


def is_true(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true", "t", "yes", "y")


def build_proxies(proxy: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """Build a requests ``proxies`` dict from the add-on proxy settings stanza."""
    if not proxy or not is_true(proxy.get("proxy_enabled")):
        return None
    host = (proxy.get("proxy_url") or "").strip()
    port = str(proxy.get("proxy_port") or "").strip()
    if not host or not port:
        return None
    proxy_type = (proxy.get("proxy_type") or "http").strip().lower()
    if proxy_type == "socks5":
        scheme = "socks5h" if is_true(proxy.get("proxy_rdns")) else "socks5"
    else:
        scheme = "http"
    auth = ""
    user = proxy.get("proxy_username")
    if user:
        auth = quote(user, safe="")
        password = proxy.get("proxy_password")
        if password:
            auth += ":" + quote(password, safe="")
        auth += "@"
    url = "{}://{}{}:{}".format(scheme, auth, host, port)
    return {"http": url, "https": url}


class AuditLogClient:
    def __init__(
        self,
        api_key: str,
        key_type: str = "team",
        team_id: Optional[str] = None,
        proxies: Optional[Dict[str, str]] = None,
        timeout: float = 120.0,
        max_retries: int = 6,
        backoff_cap: float = 90.0,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        session: Optional[requests.Session] = None,
        logger: Optional[logging.Logger] = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        base_url: str = API_BASE,
    ):
        if not api_key or not str(api_key).strip():
            raise ValueError("API key is required.")
        if key_type not in PATHS:
            raise ValueError("Key type must be 'team' or 'organization'.")
        if team_id not in (None, "") and not str(team_id).strip().isdigit():
            raise ValueError("Team ID must be numeric.")
        if not base_url.startswith("https://"):
            raise ValueError("API base URL must use HTTPS.")
        self.base_url = base_url.rstrip("/")
        self.path = PATHS[key_type]
        self.key_type = key_type
        self.team_id = str(team_id).strip() if key_type == "organization" and team_id not in (None, "") else None
        self._api_key = str(api_key).strip()
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_cap = backoff_cap
        self._min_interval = min_interval_s
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request: Optional[float] = None
        self.log = logger or logging.getLogger(__name__)
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        if proxies:
            self.session.proxies.update(proxies)
            # Do not let environment proxy variables override explicit settings.
            self.session.trust_env = False

    # -- public -------------------------------------------------------------
    def list_events(
        self,
        start_ms: int,
        end_ms: int,
        page: int = 1,
        page_size: int = MAX_PAGE_SIZE,
        event_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """One page of audit events with timestamps in [start_ms, end_ms], oldest first."""
        if end_ms < start_ms or end_ms - start_ms > MAX_RANGE_MS:
            raise ValueError("Time range must be between 0 and 30 days.")
        params: List[Tuple[str, Any]] = [
            ("startTime", int(start_ms)),
            ("endTime", int(end_ms)),
            ("page", max(1, int(page))),
            ("pageSize", max(1, min(int(page_size), MAX_PAGE_SIZE))),
        ]
        if event_types:
            params.append(("eventTypes", ",".join(event_types)))
        if self.team_id:
            params.append(("teamId", self.team_id))
        body = self._get(params)
        if not isinstance(body, dict) or not isinstance(body.get("events", []), list):
            raise CursorApiError(200, "Unexpected audit log response format.")
        return body

    def test_connection(self, now_ms: Optional[int] = None) -> None:
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        self.list_events(now_ms - 3600 * 1000, now_ms, page=1, page_size=1)

    # -- transport ----------------------------------------------------------
    def _backoff(self, attempt: int, retry_after: Optional[str]) -> float:
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), self._backoff_cap)
            except ValueError:
                pass
        return min(self._backoff_cap, (2 ** attempt) * 3 + random.uniform(0, 1))  # noqa: S311 - jitter

    def _throttle(self) -> None:
        if self._last_request is not None:
            wait = self._min_interval - (self._monotonic() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._monotonic()

    def _get(self, params: List[Tuple[str, Any]]) -> Any:
        url = self.base_url + self.path
        attempt = 0
        while True:
            self._throttle()
            try:
                resp = self.session.get(
                    url, params=params, auth=(self._api_key, ""),
                    headers={"Accept": "application/json"}, timeout=self._timeout, verify=True,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt >= self._max_retries:
                    raise
                wait = self._backoff(attempt, None)
                self.log.warning("GET %s failed (%s); retrying in %.1fs", self.path, type(exc).__name__, wait)
                self._sleep(wait)
                attempt += 1
                continue

            if resp.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                wait = self._backoff(attempt, resp.headers.get("Retry-After"))
                self.log.warning("GET %s returned HTTP %s; retrying in %.1fs", self.path, resp.status_code, wait)
                self._sleep(wait)
                attempt += 1
                continue

            if resp.status_code >= 400:
                message = _ERROR_HINTS.get(resp.status_code, resp.reason or "request failed")
                try:
                    payload = resp.json() or {}
                    api_message = payload.get("error") or payload.get("message")
                    if isinstance(api_message, dict):
                        api_message = api_message.get("message")
                except (ValueError, AttributeError):
                    api_message = None
                if api_message:
                    message = "{} API says: {}".format(message, str(api_message)[:300])
                raise CursorApiError(resp.status_code, message)

            try:
                return resp.json()
            except ValueError as exc:
                raise CursorApiError(resp.status_code, "Response is not valid JSON.") from exc
