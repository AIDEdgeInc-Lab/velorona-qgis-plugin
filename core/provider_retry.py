"""Bounded backoff for the live public data services, and an honest classification of their failures. Pure stdlib -- runs without QGIS.

A rate limit or an outage of Open-Meteo is a statement about the SERVICE, never about the link. Three rules:

1. Only failures that can go away are retried: HTTP 429, HTTP 5xx, timeouts and connection errors, up to ``len(RETRY_DELAYS_S)`` more times,
   waiting the server's ``Retry-After`` (capped) or the delay below. Everything else (HTTP 4xx other than 429, a wrong value count, bad data) is
   deterministic and is never retried.
2. A *daily* limit ("Daily API request limit exceeded") is not retried at all: no delay within the day helps, and hammering a hard limit is rude.
3. When retries are exhausted the caller raises NO DATA (owner-approved T1/R5/T3) with ``transient=True`` and a reason that names the real
   cause ("rate-limited", "daily limit", "server error", "network") -- the failure is not presented as anything the link did, and is never cached
   as a result. No status other than NO DATA is ever derived from a failed fetch.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

RETRY_DELAYS_S = (1.0, 3.0)      # PROPOSED: two more attempts, at most 4 s of waiting in the GUI thread
MAX_RETRY_AFTER_S = 10.0         # PROPOSED: a longer Retry-After is not waited for; the failure is reported instead


def _sleep(seconds: float) -> None:      # module-level so tests can replace it
    time.sleep(seconds)


@dataclass(frozen=True)
class Failure:
    transient: bool                 # may succeed later
    daily: bool                     # a per-day quota: retrying today is pointless
    status: Optional[int]
    retry_after: Optional[float]
    kind: str                       # "rate limit" | "daily limit" | "server error" | "network" | "client error" | "other"

    def reason(self, exc: BaseException) -> str:
        detail = str(exc)
        detail = (detail[:117] + "...") if len(detail) > 120 else detail
        if self.daily:
            return f"the service's daily request limit is used up (HTTP {self.status}); try again after 00:00 UTC. {detail}"
        if self.kind == "rate limit":
            return f"the service is rate-limiting requests (HTTP {self.status}); try again in a minute. {detail}"
        if self.kind == "server error":
            return f"the service answered a server error (HTTP {self.status}); try again later. {detail}"
        if self.kind == "network":
            return f"the service could not be reached; check the connection. {detail}"
        return detail


def classify(exc: BaseException) -> Failure:
    import requests
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status is None:
        match = re.match(r"\s*(\d{3})\b", str(exc))
        status = int(match.group(1)) if match else None
    text = ""
    try:
        text = (getattr(response, "text", "") or "").lower()
    except Exception:       # a response whose body cannot be read is classified by status alone
        pass
    retry_after = None
    try:
        header = (getattr(response, "headers", None) or {}).get("Retry-After")
        retry_after = float(header) if header is not None else None
    except (TypeError, ValueError):
        retry_after = None
    if status == 429:
        daily = "daily" in text
        return Failure(transient=True, daily=daily, status=status, retry_after=retry_after, kind="daily limit" if daily else "rate limit")
    if status is not None and 500 <= status <= 599:
        return Failure(True, False, status, retry_after, "server error")
    if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        return Failure(True, False, status, retry_after, "network")
    if status is not None and 400 <= status <= 499:
        return Failure(False, False, status, None, "client error")
    return Failure(False, False, status, None, "other")


def call_with_backoff(fn: Callable, retryable: tuple = (Exception,)):
    """Call ``fn()``; on a transient, non-daily failure wait and try again (bounded); otherwise re-raise the ORIGINAL exception.

    ``retryable`` limits which exception types are inspected at all (anything else propagates untouched, so a real bug is never swallowed)."""
    delays = tuple(RETRY_DELAYS_S)
    attempt = 0
    while True:
        try:
            return fn()
        except retryable as exc:
            failure = classify(exc)
            if not failure.transient or failure.daily or attempt >= len(delays):
                raise
            wait = delays[attempt]
            if failure.retry_after is not None:
                if failure.retry_after > MAX_RETRY_AFTER_S:
                    raise
                wait = max(wait, failure.retry_after)
            _sleep(wait)
            attempt += 1
