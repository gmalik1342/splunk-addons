"""HTTP client for the VeeOne open API (specialist stats).

Sends the API key in the ``X-API-Key`` header, only talks HTTPS, always
verifies TLS, and retries transient failures with exponential backoff
(honouring ``Retry-After``).
"""

from __future__ import annotations

import logging
import random
import re
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

import requests

from . import USER_AGENT

SPECIALIST_STATS_PATH = "/api/v2/specialist/stats"
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+(:\d{1,5})?$")
# Response keys that may wrap the record list, if the API returns an object.
_LIST_KEYS = ("data", "items", "results", "specialists")

_ERROR_HINTS = {
    400: "Bad request; the API rejected the request.",
    401: "Authentication failed; check the API key.",
    403: "The API key is not allowed to read specialist stats.",
    404: "Endpoint not found; check the API Base URL.",
}


class VeeOneApiError(Exception):
    """Raised when the VeeOne API returns an error that should not be retried."""

    def __init__(self, status: int, message: str):
        super().__init__("HTTP {}: {}".format(status, message))
        self.status = status


def normalize_base_url(value: str) -> str:
    """Return ``https://<host>[:port]`` for a user-supplied base URL or host.

    Raises ValueError for non-HTTPS URLs, paths or anything that isn't a host.
    """
    if not value or not value.strip():
        raise ValueError("API Base URL is required.")
    url = value.strip().rstrip("/")
    lowered = url.lower()
    if lowered.startswith("http://"):
        raise ValueError("API Base URL must use HTTPS.")
    if lowered.startswith("https://"):
        url = url[len("https://"):]
    if "/" in url or not _HOST_RE.match(url):
        raise ValueError(
            "API Base URL must be the API host only, e.g. https://openapi.veeone.io"
        )
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


def extract_records(body: Any) -> List[Dict[str, Any]]:
    """Turn the API response body into a list of records (one event each)."""
    if isinstance(body, list):
        return [r if isinstance(r, dict) else {"value": r} for r in body]
    if isinstance(body, dict):
        for key in _LIST_KEYS:
            if isinstance(body.get(key), list):
                return extract_records(body[key])
        return [body]
    if body is None:
        return []
    raise ValueError("Unexpected response type: {}".format(type(body).__name__))


class VeeOneClient:
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
            raise ValueError("API key is required.")
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

    def get(self, path: str) -> Any:
        url = self.base_url + path
        headers = {
            "X-API-Key": self._api_key,
            "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
        }
        attempt = 0
        while True:
            try:
                resp = self.session.get(url, headers=headers, timeout=self._timeout)
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
                raise VeeOneApiError(resp.status_code, hint)

            try:
                return resp.json()
            except ValueError as exc:
                raise VeeOneApiError(resp.status_code, "Response is not valid JSON.") from exc

    def fetch_specialist_stats(self) -> List[Dict[str, Any]]:
        return extract_records(self.get(SPECIALIST_STATS_PATH))
