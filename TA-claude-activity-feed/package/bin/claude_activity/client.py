"""HTTP client for the Anthropic Compliance API Activity Feed.

``GET https://api.anthropic.com/v1/compliance/activities`` with an Admin API
key (or a Compliance Access Key) carrying the ``read:compliance_activities``
scope. Always verifies TLS and retries 429/5xx/connection errors with
exponential backoff (honouring ``retry-after``).
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

from . import USER_AGENT

API_BASE = "https://api.anthropic.com"
ACTIVITIES_PATH = "/v1/compliance/activities"
ANTHROPIC_VERSION = "2026-10-21"
MAX_LIMIT = 5000
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504, 529})

_ERROR_HINTS = {
    400: "Bad request; check the start time and activity type filter.",
    401: "Authentication failed; check the API key (an Admin API key, sk-ant-admin01-...).",
    403: "The key cannot read the Activity Feed; it needs the read:compliance_activities scope "
         "and the Compliance API must be enabled for the organization.",
    404: "Endpoint not found; the Compliance API may not be available for this organization.",
}


class AnthropicApiError(Exception):
    """Raised when the Anthropic API returns an error that should not be retried."""

    def __init__(self, status: int, message: str, request_id: Optional[str] = None):
        detail = " (request-id {})".format(request_id) if request_id else ""
        super().__init__("HTTP {}: {}{}".format(status, message, detail))
        self.status = status
        self.request_id = request_id


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


class ActivityFeedClient:
    def __init__(
        self,
        api_key: str,
        proxies: Optional[Dict[str, str]] = None,
        timeout: float = 120.0,
        max_retries: int = 6,
        backoff_cap: float = 60.0,
        session: Optional[requests.Session] = None,
        logger: Optional[logging.Logger] = None,
        sleep: Callable[[float], None] = time.sleep,
        base_url: str = API_BASE,
    ):
        if not api_key or not str(api_key).strip():
            raise ValueError("API key is required.")
        if not base_url.startswith("https://"):
            raise ValueError("API base URL must use HTTPS.")
        self.base_url = base_url.rstrip("/")
        self._api_key = str(api_key).strip()
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_cap = backoff_cap
        self._sleep = sleep
        self.log = logger or logging.getLogger(__name__)
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        if proxies:
            self.session.proxies.update(proxies)
            # Do not let environment proxy variables override explicit settings.
            self.session.trust_env = False

    def _backoff(self, attempt: int, retry_after: Optional[str]) -> float:
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), self._backoff_cap)
            except ValueError:
                pass
        return min(self._backoff_cap, (2 ** attempt) + random.uniform(0, 1))

    def list_activities(
        self,
        created_gte: str,
        created_lt: str,
        after_id: Optional[str] = None,
        limit: int = 1000,
        activity_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """One page of the Activity Feed (newest first) within [created_gte, created_lt)."""
        params: List[Tuple[str, Any]] = [
            ("created_at.gte", created_gte),
            ("created_at.lt", created_lt),
            ("limit", max(1, min(int(limit), MAX_LIMIT))),
        ]
        if after_id:
            params.append(("after_id", after_id))
        for activity_type in activity_types or []:
            params.append(("activity_types[]", activity_type))
        body = self._get(ACTIVITIES_PATH, params)
        if not isinstance(body, dict) or not isinstance(body.get("data", []), list):
            raise AnthropicApiError(200, "Unexpected Activity Feed response format.")
        return body

    def test_connection(self) -> None:
        self._get(ACTIVITIES_PATH, [("limit", 1)])

    def _get(self, path: str, params: List[Tuple[str, Any]]) -> Any:
        url = self.base_url + path
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Accept": "application/json",
        }
        attempt = 0
        while True:
            try:
                resp = self.session.get(url, params=params, headers=headers, timeout=self._timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt >= self._max_retries:
                    raise
                wait = self._backoff(attempt, None)
                self.log.warning("GET %s failed (%s); retrying in %.1fs", path, type(exc).__name__, wait)
                self._sleep(wait)
                attempt += 1
                continue

            request_id = resp.headers.get("request-id")
            if resp.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                wait = self._backoff(attempt, resp.headers.get("retry-after"))
                self.log.warning(
                    "GET %s returned HTTP %s (request-id %s); retrying in %.1fs",
                    path, resp.status_code, request_id, wait,
                )
                self._sleep(wait)
                attempt += 1
                continue

            if resp.status_code >= 400:
                message = _ERROR_HINTS.get(resp.status_code, resp.reason or "request failed")
                try:
                    api_message = ((resp.json() or {}).get("error") or {}).get("message")
                except (ValueError, AttributeError):
                    api_message = None
                if api_message:
                    message = "{} API says: {}".format(message, api_message)
                raise AnthropicApiError(resp.status_code, message, request_id)

            try:
                return resp.json()
            except ValueError as exc:
                raise AnthropicApiError(resp.status_code, "Response is not valid JSON.", request_id) from exc
