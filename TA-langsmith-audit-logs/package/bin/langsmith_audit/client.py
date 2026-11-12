"""HTTP client for the LangSmith audit log API.

``GET {base}/api/v1/audit-logs`` with ``X-API-Key`` and ``X-Organization-Id``
headers (Enterprise; Organization Admin or Operator). ``start_time`` and
``end_time`` (ISO 8601, both inclusive and required), ``limit`` 1-100,
``cursor`` for the next page. Items are OCSF v1.7 API Activity (class 6003).
TLS is always verified; 429/5xx and connection errors are retried with
exponential backoff, honouring ``Retry-After``.
"""

from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

import requests

from . import USER_AGENT

REGIONS = {
    "us": "https://api.smith.langchain.com",
    "eu": "https://eu.api.smith.langchain.com",
    "apac": "https://apac.api.smith.langchain.com",
    "aws_us": "https://aws.api.smith.langchain.com",
}
AUDIT_PATH = "/api/v1/audit-logs"
MAX_LIMIT = 100
DEFAULT_MIN_INTERVAL_S = 0.25
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

_ERROR_HINTS = {
    401: "Authentication failed; check the API key.",
    403: "The key cannot read audit logs. Audit logs need a LangSmith Enterprise plan and a key "
         "belonging to an Organization Admin or Organization Operator, and the Organization ID must match the key.",
    404: "Endpoint not found; check the region or self-hosted URL (self-hosted needs audit logs enabled, Helm chart 0.12.33+).",
    422: "LangSmith rejected the request parameters; check the start time and operation filter.",
}


class LangSmithApiError(Exception):
    """Raised when the LangSmith API returns an error that should not be retried."""

    def __init__(self, status: int, message: str):
        super().__init__("HTTP {}: {}".format(status, message))
        self.status = status


def is_true(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true", "t", "yes", "y")


def resolve_base_url(region: Optional[str], custom_url: Optional[str] = None) -> str:
    """Region key -> API base URL; 'custom' uses a self-hosted HTTPS URL (scheme + host[:port])."""
    region = (region or "us").strip().lower()
    if region in REGIONS:
        return REGIONS[region]
    if region != "custom":
        raise ValueError("Unknown region '{}'.".format(region))
    url = (custom_url or "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Self-hosted URL must be an HTTPS URL such as https://langsmith.example.com")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Self-hosted URL must be the host only, without a path.")
    return "https://" + parsed.netloc


def format_iso_ms(epoch_ms: int) -> str:
    dt = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(int(epoch_ms) % 1000)


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
        organization_id: str,
        base_url: str = REGIONS["us"],
        workspace_id: Optional[str] = None,
        proxies: Optional[Dict[str, str]] = None,
        timeout: float = 120.0,
        max_retries: int = 6,
        backoff_cap: float = 60.0,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        session: Optional[requests.Session] = None,
        logger: Optional[logging.Logger] = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        if not api_key or not str(api_key).strip():
            raise ValueError("API key is required.")
        if not organization_id or not _UUID.match(str(organization_id).strip()):
            raise ValueError("Organization ID must be a UUID.")
        if workspace_id not in (None, "") and not _UUID.match(str(workspace_id).strip()):
            raise ValueError("Workspace ID must be a UUID.")
        if not base_url.startswith("https://"):
            raise ValueError("API base URL must use HTTPS.")
        self.base_url = base_url.rstrip("/")
        self._api_key = str(api_key).strip()
        self._org_id = str(organization_id).strip()
        self.workspace_id = str(workspace_id).strip() if workspace_id not in (None, "") else None
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
    def list_audit_logs(
        self,
        start_ms: int,
        end_ms: int,
        cursor: Optional[str] = None,
        limit: int = MAX_LIMIT,
        operations: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """One page of audit events with time in [start_ms, end_ms] (both inclusive)."""
        if end_ms < start_ms:
            raise ValueError("end_ms must not be before start_ms.")
        params: List[Tuple[str, Any]] = [
            ("start_time", format_iso_ms(start_ms)),
            ("end_time", format_iso_ms(end_ms)),
            ("limit", max(1, min(int(limit), MAX_LIMIT))),
        ]
        if cursor:
            params.append(("cursor", cursor))
        if self.workspace_id:
            params.append(("workspace_id", self.workspace_id))
        for op in operations or []:
            params.append(("operations", op))
        body = self._get(AUDIT_PATH, params)
        if not isinstance(body, dict) or not isinstance(body.get("items", []), list):
            raise LangSmithApiError(200, "Unexpected audit log response format.")
        return body

    def test_connection(self, now_ms: Optional[int] = None) -> None:
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        self.list_audit_logs(now_ms - 3600 * 1000, now_ms, limit=1)

    # -- transport ----------------------------------------------------------
    def _backoff(self, attempt: int, retry_after: Optional[str]) -> float:
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), self._backoff_cap)
            except ValueError:
                pass
        return min(self._backoff_cap, (2 ** attempt) + random.uniform(0, 1))  # noqa: S311 - jitter

    def _throttle(self) -> None:
        if self._last_request is not None and self._min_interval > 0:
            wait = self._min_interval - (self._monotonic() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._monotonic()

    def _get(self, path: str, params: List[Tuple[str, Any]]) -> Any:
        url = self.base_url + path
        headers = {
            "X-API-Key": self._api_key,
            "X-Organization-Id": self._org_id,
            "Accept": "application/json",
        }
        attempt = 0
        while True:
            self._throttle()
            try:
                resp = self.session.get(url, params=params, headers=headers,
                                        timeout=self._timeout, verify=True)
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
                message = _ERROR_HINTS.get(resp.status_code, resp.reason or "request failed")
                try:
                    detail = (resp.json() or {}).get("detail")
                except (ValueError, AttributeError):
                    detail = None
                if detail:
                    message = "{} API says: {}".format(message, str(detail)[:300])
                raise LangSmithApiError(resp.status_code, message)

            try:
                return resp.json()
            except ValueError as exc:
                raise LangSmithApiError(resp.status_code, "Response is not valid JSON.") from exc
