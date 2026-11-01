"""
brightsky/client.py — The HTTP client for the BrightSky backend.

The other half of the trust boundary to the backend (config.py is the first).
The bridge token goes out on every request and nowhere else: no log line, no
error message. Every body that comes back is read with models.py's validating
readers.

Retry policy, in `_request` only: a status >= 500 or an `OSError` (which covers
`URLError` and `TimeoutError`) is retried exactly once after a short jittered
backoff; a 4xx is never retried. `report_run` resends the identical body, so
the backend dedupes it by idempotency key. `propose_version` re-reads the
workflow before its retry and takes a version with the same note as success,
so a POST the server stored before failing is not stored twice.

Stdlib only (`urllib`): spec.md, Decisions, "HTTP client".
"""

from __future__ import annotations

import http.client
import json
import logging
import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

from stepper.brightsky.config import LOOPBACK_HOSTS, BrightSkyConfig
from stepper.brightsky.models import (
    SLUG_PATTERN,
    BrightSkyResponseError,
    Proposal,
    QueueItem,
    RunReport,
    WorkflowDetail,
)

__all__ = [
    "TIMEOUT", "BrightSkyClient", "BrightSkyHttpError", "BrightSkyResponseError",
    "HttpResponse", "Transport", "UrllibTransport",
]

logger = logging.getLogger(__name__)

#: Seconds urllib waits on each socket operation (connect, each read); it is not
#: a total deadline, so a backend that trickles bytes can hold a request longer.
TIMEOUT = 20.0
#: The longest backend message kept in an error.
MAX_MESSAGE = 500
#: The largest response body read, in bytes; a larger one is a failed response.
MAX_BODY = 4 * 1024 * 1024

QUEUE_PATH = "/api/workflows/verification-queue"


class BrightSkyHttpError(Exception):
    """A request failed for good: a 4xx, or a 5xx / network error after the retry.

    `status` is 0 for a network error. Neither field ever holds the token.
    """

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(f"HTTP {status}: {message}" if status else message)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes


class Transport(Protocol):
    def send(self, method: str, url: str, headers: dict[str, str],
             body: bytes | None, timeout: float) -> HttpResponse:
        """Send one request. An HTTP error status is returned; a network failure
        raises OSError."""
        ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib forwards the Authorization header on a redirect, to any host and
    scheme; the backend's API never redirects, so a 3xx is returned as is."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrllibTransport:
    """The default transport. Loopback hosts bypass environment proxies
    (`ProxyHandler({})`, see map.md for the source); others use the default handlers."""

    def __init__(self) -> None:
        self._direct = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                   _NoRedirect)
        self._default = urllib.request.build_opener(_NoRedirect)

    def send(self, method: str, url: str, headers: dict[str, str],
             body: bytes | None, timeout: float) -> HttpResponse:
        opener = self._direct if urlsplit(url).hostname in LOOPBACK_HOSTS else self._default
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            try:
                with opener.open(request, timeout=timeout) as response:
                    return HttpResponse(status=response.status, body=_read_capped(response))
            except urllib.error.HTTPError as err:
                # HTTPError is an OSError too; an error status is an answer, not a failure.
                with err:
                    return HttpResponse(status=err.code, body=_read_capped(err))
        except http.client.HTTPException as err:
            # Outer try: a broken error body, read in the handler above, lands here too.
            # A malformed or cut-off response is a network failure to the caller.
            raise OSError(f"bad HTTP response: {type(err).__name__}") from err


def _read_capped(response: Any) -> bytes:
    """Read at most MAX_BODY bytes; a longer body, or one shorter than its
    Content-Length, raises OSError (a failed response)."""
    body = response.read(MAX_BODY + 1)
    if len(body) > MAX_BODY:
        raise OSError(f"response body is larger than {MAX_BODY} bytes")
    # http.client counts down `length` (None when chunked or unsized) and returns a
    # short read without error when the connection closes early.
    missing = getattr(response, "length", None)
    if isinstance(missing, int) and missing > 0:
        raise OSError(f"response body is shorter than its Content-Length by {missing} bytes")
    return body


class BrightSkyClient:
    def __init__(self, config: BrightSkyConfig, transport: Transport | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._config = config
        self._transport = transport if transport is not None else UrllibTransport()
        self._sleep = sleep

    # ── calls ────────────────────────────────────────────────────────────────

    def queue(self) -> tuple[list[QueueItem], list[str]]:
        """The unverified versions in the backend's order, and one reason for
        each malformed entry, which is left out."""
        raw = _json(self._request("GET", QUEUE_PATH))
        if not isinstance(raw, list):
            raise BrightSkyResponseError("the verification queue must be a list")
        items: list[QueueItem] = []
        rejected: list[str] = []
        for number, entry in enumerate(raw, start=1):
            try:
                items.append(QueueItem.from_json(entry))
            except BrightSkyResponseError as err:
                rejected.append(f"entry {number}: {err}")
        return items, rejected

    def get_workflow(self, slug: str) -> WorkflowDetail:
        return WorkflowDetail.from_json(_json(self._request("GET", _workflow_path(slug))))

    def report_run(self, slug: str, report: RunReport) -> None:
        # One encoded body for both attempts: the retry is byte-identical.
        self._request("POST", _workflow_path(slug) + "/runs", _encode(report.to_json()))

    def propose_version(self, slug: str, proposal: Proposal) -> int:
        """Post a new unverified version and return its number."""
        path = _workflow_path(slug) + "/versions"
        stored: list[int] = []

        def already_stored() -> bool:
            # The first POST may have been stored before it failed.
            for number, note in self.get_workflow(slug).versions:
                if note == proposal.note:
                    stored.append(number)
                    return True
            return False

        raw = self._request("POST", path, _encode(proposal.to_json()),
                            before_retry=already_stored)
        if raw is None:
            return stored[0]
        created = _json(raw)
        number = created.get("version") if isinstance(created, dict) else None
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise BrightSkyResponseError("the new version's version must be an integer >= 1")
        return number

    # ── the retry policy ─────────────────────────────────────────────────────

    def _request(self, method: str, path: str, body: bytes | None = None, *,
                 before_retry: Callable[[], bool] | None = None) -> bytes | None:
        """Send with one retry. Returns the 2xx body, or None when `before_retry`
        found the work already done. Raises BrightSkyHttpError."""
        headers = {"Authorization": f"Bearer {self._config.token}",
                   "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        url = self._config.api_url + path

        for attempt in (1, 2):
            if attempt == 2:
                self._sleep(1.0 + random.uniform(0, 0.5))
                if before_retry is not None:
                    try:
                        done = before_retry()
                    except (BrightSkyHttpError, BrightSkyResponseError) as err:
                        # Unsure whether the first attempt was stored: do not send
                        # again; report the first attempt's error, the re-read's chained.
                        logger.warning("brightsky re-read before retry failed method=%s "
                                       "path=%s error=%s", method, path, type(err).__name__)
                        raise failure from err
                    if done:
                        return None
            started = time.monotonic()
            try:
                response = self._transport.send(method, url, headers, body, TIMEOUT)
            except OSError as err:
                self._log(method, path, 0, attempt, started, type(err).__name__)
                failure = BrightSkyHttpError(
                    0, self._scrub(f"network error: {type(err).__name__}: {err}"))
                continue
            self._log(method, path, response.status, attempt, started)
            if 200 <= response.status < 300:
                return response.body
            failure = BrightSkyHttpError(response.status, self._message(response))
            if response.status < 500:
                break
        raise failure

    def _message(self, response: HttpResponse) -> str:
        """The backend's JSON `message` (NestJS sends a string or a list of
        strings), else the status's reason phrase."""
        try:
            message: Any = json.loads(response.body.decode("utf-8")).get("message")
        except (ValueError, UnicodeDecodeError, AttributeError, RecursionError):
            message = None
        if isinstance(message, list) and all(isinstance(m, str) for m in message):
            message = "; ".join(message)
        if not isinstance(message, str) or not message.strip():
            try:
                message = HTTPStatus(response.status).phrase
            except ValueError:
                message = "error"
        # Scrub before the cut, so a token across the cut is still replaced whole;
        # control characters become spaces so the message cannot forge log lines.
        message = "".join(c if c.isprintable() else " " for c in self._scrub(message))
        return message[:MAX_MESSAGE]

    def _scrub(self, text: str) -> str:
        return text.replace(self._config.token, "<token>")

    @staticmethod
    def _log(method: str, path: str, status: int, attempt: int, started: float,
             error: str = "") -> None:
        duration_ms = round((time.monotonic() - started) * 1000)
        level = logging.INFO if 200 <= status < 300 else logging.WARNING
        logger.log(level, "brightsky request method=%s path=%s status=%s attempt=%s "
                   "duration_ms=%s%s", method, path, status, attempt, duration_ms,
                   f" error={error}" if error else "")


def _workflow_path(slug: str) -> str:
    """Checked before any request, so a slug can never reshape the URL."""
    if not isinstance(slug, str) or not SLUG_PATTERN.fullmatch(slug):
        raise ValueError(f"slug {slug!r} is not a valid slug")
    return "/api/workflows/" + quote(slug, safe="")


def _encode(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _json(raw: bytes | None) -> Any:
    try:
        return json.loads((raw or b"").decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise BrightSkyResponseError("the response body is not JSON") from None
