"""HTTP client for the NetApp Cloud Insights Workload Security (Cloud Secure) API.

Sends the API access token in the ``X-CloudInsights-ApiKey`` header, only
talks HTTPS, always verifies TLS, and retries transient failures with
exponential backoff (honouring ``Retry-After``).
"""

from __future__ import annotations

import logging
import random
import re
import time
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote

import requests

from . import USER_AGENT

ALERTS_PATH = "/rest/v1/cloudsecure/alerts"
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+(:\d{1,5})?$")

_ERROR_HINTS = {
    400: "Bad request; the API rejected the request.",
    401: "Authentication failed; check the API access token.",
    403: "The API access token is not allowed to read Workload Security alerts.",
    404: "Endpoint not found; check the Tenant URL.",
}


class CloudSecureApiError(Exception):
    """Raised when the Cloud Secure API returns an error that should not be retried."""

    def __init__(self, status: int, message: str):
        super().__init__("HTTP {}: {}".format(status, message))
        self.status = status


def normalize_base_url(value: str) -> str:
    """Return ``https://<host>[:port]`` for a user-supplied tenant URL.

    Accepts the bare host, ``https://<host>``, or a pasted API URL under
    ``/rest/`` (e.g. the 1.0.x ``.../rest/v1/cloudsecure/alerts`` REST URL), whose
    path is dropped. Raises ValueError for non-HTTPS URLs or anything else.
    """
    if not value or not value.strip():
        raise ValueError("Tenant URL is required.")
    url = value.strip().rstrip("/")
    lowered = url.lower()
    if lowered.startswith("http://"):
        raise ValueError("Tenant URL must use HTTPS.")
    if lowered.startswith("https://"):
        url = url[len("https://"):]
    if "/" in url:
        host, path = url.split("/", 1)
        if not ("/" + path).startswith("/rest/"):
            raise ValueError("Tenant URL must be the tenant host, e.g. https://xyzcorp.c01.cloudinsights.netapp.com")
        url = host
    if not _HOST_RE.match(url):
        raise ValueError("Tenant URL must be the tenant host, e.g. https://xyzcorp.c01.cloudinsights.netapp.com")
    return "https://" + url


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


class CloudSecureClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        proxies: Optional[Dict[str, str]] = None,
        timeout: float = 120.0,
        max_retries: int = 5,
        backoff_cap: float = 60.0,
        session: Optional[requests.Session] = None,
        logger: Optional[logging.Logger] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not api_key:
            raise ValueError("API access token is required.")
        self.base_url = normalize_base_url(base_url)
        self._api_key = api_key
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
                return min(float(retry_after), self._backoff_cap)
            except ValueError:
                pass
        return min(self._backoff_cap, (2 ** attempt) + random.uniform(0, 1))

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = self.base_url + path
        headers = {
            "X-CloudInsights-ApiKey": self._api_key,
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

            if resp.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                wait = self._backoff(attempt, resp.headers.get("Retry-After"))
                self.log.warning("GET %s returned HTTP %s; retrying in %.1fs", path, resp.status_code, wait)
                self._sleep(wait)
                attempt += 1
                continue

            if resp.status_code >= 400:
                hint = _ERROR_HINTS.get(resp.status_code, resp.reason or "request failed")
                raise CloudSecureApiError(resp.status_code, hint)

            try:
                return resp.json()
            except ValueError as exc:
                raise CloudSecureApiError(resp.status_code, "Response is not valid JSON.") from exc

    def get_alerts(self, limit: int, offset: int, time_range: str = "ONE_WEEK") -> Dict[str, Any]:
        """One page of alerts, oldest first: ``{"count", "limit", "offset", "results": [...]}``."""
        body = self.get(
            ALERTS_PATH,
            params={"limit": limit, "offset": offset, "timeRange": time_range, "sort": "alertTimestamp"},
        )
        if not isinstance(body, dict) or not isinstance(body.get("results", []), list):
            raise CloudSecureApiError(200, "Unexpected alerts response format.")
        return body
