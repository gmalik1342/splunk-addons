"""HTTP client for the Cortex public API audit endpoints.

Supports Standard and Advanced API keys, retries transient failures with
exponential backoff (honouring Retry-After), always verifies TLS and only
talks HTTPS.
"""

from __future__ import annotations

import hashlib
import logging
import random
import re
import secrets
import string
import time
from typing import Any, Callable, Dict, Iterator, List, Optional
from urllib.parse import quote

import requests

from . import USER_AGENT

PAGE_SIZE = 100  # documented maximum result set per request
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_HOST_RE = re.compile(r"^api-[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9](:\d{1,5})?$")
_NONCE_ALPHABET = string.ascii_letters + string.digits

_ERROR_HINTS = {
    400: "Bad request; the API rejected the request body.",
    401: "Authentication failed; check the API URL, API Key ID, API Key and key type.",
    402: "The tenant does not have the license required for this API.",
    403: "The API key lacks the RBAC permissions required for audit logs.",
}


class CortexApiError(Exception):
    """Raised when the Cortex API returns an error that should not be retried."""

    def __init__(self, status: int, message: str, err_code: Any = None):
        super().__init__("HTTP {}: {}".format(status, message))
        self.status = status
        self.err_code = err_code


def normalize_api_url(value: str) -> str:
    """Return ``https://<host>`` for a user-supplied API URL or host.

    Raises ValueError for anything other than an HTTPS ``api-`` host.
    """
    if not value or not value.strip():
        raise ValueError("API URL is required.")
    url = value.strip().rstrip("/")
    lowered = url.lower()
    if lowered.startswith("http://"):
        raise ValueError("API URL must use HTTPS.")
    if lowered.startswith("https://"):
        url = url[len("https://"):]
    if "/" in url or not _HOST_RE.match(url):
        raise ValueError(
            "API URL must be the tenant API host beginning with 'api-', "
            "e.g. https://api-mytenant.xdr.us.paloaltonetworks.com"
        )
    return "https://" + url


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


def is_true(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true", "t", "yes", "y")


class CortexAuditClient:
    """Minimal client for POST endpoints under ``/public_api/v1``."""

    def __init__(
        self,
        api_url: str,
        api_key_id: str,
        api_key: str,
        auth_type: str = "advanced",
        proxies: Optional[Dict[str, str]] = None,
        timeout: float = 60.0,
        max_retries: int = 5,
        backoff_cap: float = 60.0,
        min_request_interval: float = 0.1,
        session: Optional[requests.Session] = None,
        logger: Optional[logging.Logger] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not api_key_id or not api_key:
            raise ValueError("API Key ID and API Key are required.")
        if auth_type not in ("standard", "advanced"):
            raise ValueError("auth_type must be 'standard' or 'advanced'.")
        self.base_url = normalize_api_url(api_url)
        self._api_key_id = str(api_key_id).strip()
        self._api_key = api_key
        self._auth_type = auth_type
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_cap = backoff_cap
        self._min_interval = min_request_interval
        self._sleep = sleep
        self._last_request = 0.0
        self.log = logger or logging.getLogger(__name__)
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        if proxies:
            self.session.proxies.update(proxies)
            # Do not let environment proxy variables override explicit settings.
            self.session.trust_env = False

    # -- auth -------------------------------------------------------------
    def _auth_headers(self) -> Dict[str, str]:
        headers = {
            "x-xdr-auth-id": self._api_key_id,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._auth_type == "advanced":
            nonce = "".join(secrets.choice(_NONCE_ALPHABET) for _ in range(64))
            timestamp = str(int(time.time() * 1000))
            digest = hashlib.sha256(
                (self._api_key + nonce + timestamp).encode("utf-8")
            ).hexdigest()
            headers.update(
                {"x-xdr-timestamp": timestamp, "x-xdr-nonce": nonce, "Authorization": digest}
            )
        else:
            headers["Authorization"] = self._api_key
        return headers

    # -- transport --------------------------------------------------------
    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            self._sleep(wait)
        self._last_request = time.monotonic()

    def _backoff(self, attempt: int, retry_after: Optional[str]) -> float:
        if retry_after:
            try:
                return min(self._backoff_cap, max(0.0, float(retry_after)))
            except ValueError:
                pass
        return min(self._backoff_cap, (2 ** attempt) + random.uniform(0, 1))  # noqa: S311 - jitter, not crypto

    def post(self, path: str, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """POST ``{"request_data": ...}`` and return the ``reply`` object."""
        url = self.base_url + path
        body = {"request_data": request_data}
        attempt = 0
        while True:
            self._throttle()
            try:
                resp = self.session.post(
                    url, json=body, headers=self._auth_headers(), timeout=self._timeout, verify=True
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt >= self._max_retries:
                    raise
                delay = self._backoff(attempt, None)
                self.log.warning(
                    "Request to %s failed (%s); retry %d/%d in %.1fs",
                    path, type(exc).__name__, attempt + 1, self._max_retries, delay,
                )
                self._sleep(delay)
                attempt += 1
                continue

            if resp.status_code == 200:
                try:
                    payload = resp.json()
                except ValueError as exc:
                    raise CortexApiError(200, "Response was not valid JSON.") from exc
                reply = payload.get("reply") if isinstance(payload, dict) else None
                if not isinstance(reply, dict):
                    raise CortexApiError(200, "Response did not contain a 'reply' object.")
                return reply

            if resp.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                delay = self._backoff(attempt, resp.headers.get("Retry-After"))
                self.log.warning(
                    "HTTP %d from %s; retry %d/%d in %.1fs",
                    resp.status_code, path, attempt + 1, self._max_retries, delay,
                )
                self._sleep(delay)
                attempt += 1
                continue

            raise self._error_from(resp)

    @staticmethod
    def _error_from(resp: requests.Response) -> CortexApiError:
        err_code = None
        detail = ""
        try:
            reply = resp.json().get("reply", {})
            if isinstance(reply, dict):
                err_code = reply.get("err_code")
                detail = " ".join(
                    str(x) for x in (reply.get("err_msg"), reply.get("err_extra")) if x
                )
        except (ValueError, AttributeError):
            detail = (resp.text or "")[:500]
        hint = _ERROR_HINTS.get(resp.status_code, "Unexpected API error.")
        message = hint + (" Details: " + detail if detail else "")
        return CortexApiError(resp.status_code, message, err_code)

    # -- pagination -------------------------------------------------------
    def iter_window(
        self,
        path: str,
        start_ms: int,
        end_ms: int,
        extra_filters: Optional[List[Dict[str, Any]]] = None,
        sort: Optional[Dict[str, str]] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Yield every record whose timestamp is within [start_ms, end_ms].

        The window is closed in the past, so offset pagination over it is
        stable regardless of the sort order the endpoint applies.
        """
        filters = [
            {"field": "timestamp", "operator": "gte", "value": int(start_ms)},
            {"field": "timestamp", "operator": "lte", "value": int(end_ms)},
        ]
        filters.extend(extra_filters or [])
        offset = 0
        total = None
        while True:
            request_data: Dict[str, Any] = {
                "filters": filters,
                "search_from": offset,
                "search_to": offset + PAGE_SIZE,
            }
            if sort:
                request_data["sort"] = sort
            reply = self.post(path, request_data)
            data = reply.get("data") or []
            if total is None:
                total = int(reply.get("total_count") or 0)
                self.log.debug("Window %d-%d on %s has %d records", start_ms, end_ms, path, total)
            for record in data:
                yield record
            offset += len(data)
            if not data or len(data) < PAGE_SIZE or offset >= total:
                return

    def test_connection(self, path: str) -> int:
        """Make a one-record request; returns total_count. Raises on failure."""
        reply = self.post(path, {"search_from": 0, "search_to": 1})
        return int(reply.get("total_count") or 0)
