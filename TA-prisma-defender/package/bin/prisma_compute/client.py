"""HTTP client for the Prisma Cloud Compute (Twistlock) Console API.

Authenticates with HTTP basic auth (access key ID / secret key, or a Console
username / password), only talks HTTPS, always verifies TLS, and retries
transient failures with exponential backoff (honouring ``Retry-After``).
"""

from __future__ import annotations

import logging
import random
import re
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

import requests
from requests.auth import HTTPBasicAuth

from . import USER_AGENT

MAX_PAGE_SIZE = 50  # Compute API maximum per paginated request
MAX_PAGES = 2000    # 100,000 Defenders
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)*(:\d{1,5})?$")
_PATH_RE = re.compile(r"^(/[A-Za-z0-9._~-]+)*$")
_VERSION_RE = re.compile(r"^v\d+(\.\d+)?$")

_ERROR_HINTS = {
    400: "Bad request; the API rejected the request.",
    401: "Authentication failed; check the access key ID and secret key.",
    403: "The access key's role cannot read this endpoint (Defenders / registry scan results).",
    404: "Endpoint not found; check the Console URL and API version.",
}


class PrismaApiError(Exception):
    """Raised when the Console API returns an error that should not be retried."""

    def __init__(self, status: int, message: str):
        super().__init__("HTTP {}: {}".format(status, message))
        self.status = status


def normalize_console_url(value: str) -> str:
    """Return ``https://<host>[:port][/path]`` for the Console address.

    SaaS consoles include a tenant path (``https://us-east1.cloud.twistlock.com/us-1-123``);
    self-hosted consoles usually listen on port 8083. Query strings, fragments and
    non-HTTPS URLs are rejected. A trailing ``/api/...`` is dropped.
    """
    if not value or not value.strip():
        raise ValueError("Console URL is required.")
    url = value.strip().rstrip("/")
    lowered = url.lower()
    if lowered.startswith("http://"):
        raise ValueError("Console URL must use HTTPS.")
    if lowered.startswith("https://"):
        url = url[len("https://"):]
    if "?" in url or "#" in url:
        raise ValueError("Console URL must not contain a query string.")
    host, _, path = url.partition("/")
    path = "/" + path if path else ""
    marker = path.find("/api/")
    if marker >= 0 or path == "/api":
        path = path[:marker] if marker >= 0 else ""
    if not _HOST_RE.match(host) or not _PATH_RE.match(path):
        raise ValueError(
            "Console URL must be the HTTPS Console address, e.g. "
            "https://us-east1.cloud.twistlock.com/us-1-123456789 or https://console.example.com:8083"
        )
    return "https://" + host + path


def normalize_api_version(value: Optional[str]) -> str:
    version = (value or "v1").strip()
    if not _VERSION_RE.match(version):
        raise ValueError("API version must look like v1 or v34.02.")
    return version


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


class PrismaClient:
    def __init__(
        self,
        console_url: str,
        access_key_id: str,
        secret_key: str,
        api_version: Optional[str] = None,
        proxies: Optional[Dict[str, str]] = None,
        timeout: float = 120.0,
        max_retries: int = 5,
        backoff_cap: float = 60.0,
        session: Optional[requests.Session] = None,
        logger: Optional[logging.Logger] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not access_key_id or not secret_key:
            raise ValueError("Access key ID and secret key are required.")
        self.base_url = normalize_console_url(console_url)
        self.api_version = normalize_api_version(api_version)
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_cap = backoff_cap
        self._sleep = sleep
        self.log = logger or logging.getLogger(__name__)
        self.session = session or requests.Session()
        self.session.auth = HTTPBasicAuth(access_key_id.strip(), secret_key)
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
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

    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None,
            headers: Optional[Dict[str, str]] = None) -> Any:
        url = "{}/api/{}/{}".format(self.base_url, self.api_version, endpoint.lstrip("/"))
        attempt = 0
        while True:
            try:
                resp = self.session.get(url, params=params, headers=headers, timeout=self._timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt >= self._max_retries:
                    raise
                wait = self._backoff(attempt, None)
                self.log.warning("GET %s failed (%s); retrying in %.1fs", endpoint, type(exc).__name__, wait)
                self._sleep(wait)
                attempt += 1
                continue

            if resp.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                wait = self._backoff(attempt, resp.headers.get("Retry-After"))
                self.log.warning("GET %s returned HTTP %s; retrying in %.1fs", endpoint, resp.status_code, wait)
                self._sleep(wait)
                attempt += 1
                continue

            if resp.status_code >= 400:
                hint = _ERROR_HINTS.get(resp.status_code, resp.reason or "request failed")
                raise PrismaApiError(resp.status_code, "{} ({})".format(hint, endpoint))

            try:
                return resp.json()
            except ValueError as exc:
                raise PrismaApiError(resp.status_code, "Response from {} is not valid JSON.".format(endpoint)) from exc

    def _list(self, endpoint: str, params: Optional[Dict[str, Any]] = None,
              headers: Optional[Dict[str, str]] = None) -> List[Any]:
        body = self.get(endpoint, params=params, headers=headers)
        if body is None:
            return []  # the Console returns null for an empty list
        if not isinstance(body, list):
            raise PrismaApiError(200, "Unexpected response format from {}.".format(endpoint))
        return body

    def defenders_summary(self) -> List[Dict[str, Any]]:
        return self._list("defenders/summary")

    def registry_progress(self) -> List[Dict[str, Any]]:
        return self._list("registry/progress", params={"onDemand": "false"})

    def iter_defenders(self, page_size: int = MAX_PAGE_SIZE):
        """Yield every Defender (connected and disconnected), paging by limit/offset."""
        page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
        offset = 0
        for _ in range(MAX_PAGES):
            page = self._list(
                "defenders",
                params={"limit": page_size, "offset": offset},
                headers={"x-prisma-cloud-target-env": '{"permission":"manageDefenders"}'},
            )
            for defender in page:
                yield defender
            if len(page) < page_size:
                return
            offset += page_size
        self.log.warning("Stopped listing Defenders after %d pages.", MAX_PAGES)
