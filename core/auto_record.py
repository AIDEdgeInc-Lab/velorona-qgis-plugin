"""Automatic recording of weather values for chosen links (opt-in, OFF by default). Pure scheduling logic; plugin.py runs the fetches.

What it promises, and nothing more:
* off at every QGIS start; the user switches it on in the History window, picks the links (the link shown in the results panel is added
  with "Record this link"), and it stops when QGIS closes or the plugin unloads. Nothing runs between QGIS sessions.
* every ``interval_min`` minutes (default 15, never less), one background round fetches the links ONE AT A TIME, with a small random delay
  so many users do not all ask at the same second;
* at most ``max_links`` links (the free plan's limit, core/entitlements.py);
* a busy service (HTTP 429, or a daily limit) stops the round at once and doubles the wait (up to 8x); three busy rounds in a row pause
  recording and say so. Other failures are recorded as failures for that link only, never as a value;
* values are stored by the same capture as a manual analysis, with the time the provider gives and the real fetch time; the user's own
  sites and links are stored under their private code, and their NAMES only when the user ticked "Include my site names" for that link.
Gaps are normal (the computer sleeps, QGIS is closed): the series is what was fetched, nothing is filled in.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

DEFAULT_INTERVAL_MIN = 15
INTERVAL_CHOICES_MIN = (15, 30, 60, 120)
MAX_BACKOFF_FACTOR = 8
PAUSE_AFTER_BUSY_ROUNDS = 3
JITTER_S = 60

# Message IDs (core/messages.py; plugin-only until the Map registry has them).
OFF, ON, LIMIT, BUSY, PAUSED, ADDED, ALREADY, NEEDS_WEATHER = (
    "I-RECORD-OFF", "I-RECORD-ON", "W-RECORD-LIMIT", "W-RECORD-BUSY", "W-RECORD-PAUSED", "I-RECORD-ADDED", "I-RECORD-ALREADY", "I-RECORD-NEEDS-WEATHER")


@dataclass
class Watched:
    key: tuple                      # core.study_export.study_key of the link
    label: str                      # what the History window shows (the user's own names only if include_names)
    public: bool                    # a public Fixed Service record (stored by its id) or the user's own sites (stored under a private code)
    include_names: bool
    request: Dict[str, Any]         # what the worker needs to fetch again (see plugin.py _record_round)
    last_ok: Optional[float] = None
    last_error: str = ""


@dataclass
class Recorder:
    max_links: int
    enabled: bool = False
    interval_min: int = DEFAULT_INTERVAL_MIN
    links: Dict[tuple, Watched] = field(default_factory=dict)
    backoff: int = 1
    busy_rounds: int = 0
    next_due: Optional[float] = None
    status_id: str = OFF
    rng: Any = field(default_factory=random.Random)

    # -- user actions --------------------------------------------------------------------------------------------------------------------

    def add(self, watched: Watched) -> str:
        if watched.key in self.links:
            self.links[watched.key] = watched          # a newer request (e.g. the names box changed) replaces the old one
            return ALREADY
        if len(self.links) >= self.max_links:
            return LIMIT
        self.links[watched.key] = watched
        return ADDED

    def remove(self, key) -> None:
        self.links.pop(key, None)

    def set_interval(self, minutes: int) -> None:
        self.interval_min = max(DEFAULT_INTERVAL_MIN, int(minutes))

    def set_enabled(self, on: bool, now: float) -> str:
        self.enabled = bool(on)
        self.backoff, self.busy_rounds = 1, 0
        self.next_due = now if self.enabled else None     # the first round runs at once, then every interval
        self.status_id = ON if self.enabled else OFF
        return self.status_id

    # -- scheduling ----------------------------------------------------------------------------------------------------------------------

    def due(self, now: float) -> bool:
        return self.enabled and bool(self.links) and self.next_due is not None and now >= self.next_due

    def round(self) -> List[Watched]:
        """The links of one round, in a stable order."""
        return [self.links[k] for k in sorted(self.links, key=str)]

    def finish_round(self, now: float, busy: bool) -> str:
        """Called once per round. ``busy``: the service refused with a rate or daily limit (the round stopped there)."""
        if busy:
            self.busy_rounds += 1
            self.backoff = min(MAX_BACKOFF_FACTOR, self.backoff * 2)
            if self.busy_rounds >= PAUSE_AFTER_BUSY_ROUNDS:
                self.enabled, self.next_due, self.status_id = False, None, PAUSED
                return PAUSED
            self.status_id = BUSY
        else:
            self.busy_rounds, self.backoff, self.status_id = 0, 1, ON
        self.next_due = now + self.wait_s()
        return self.status_id

    def wait_s(self) -> float:
        return self.interval_min * 60 * self.backoff + self.rng.uniform(0, JITTER_S)

    def stop(self) -> None:
        """QGIS is closing or the plugin unloads: nothing more runs, nothing is kept for the next session."""
        self.enabled, self.next_due, self.status_id = False, None, OFF
        self.links.clear()


def is_busy_failure(exc) -> bool:
    """A refusal that more requests would make worse: HTTP 429 or a daily request limit (core/provider_retry.py wording)."""
    text = str(exc).lower()
    return "429" in text or "rate-limiting" in text or "daily request limit" in text
