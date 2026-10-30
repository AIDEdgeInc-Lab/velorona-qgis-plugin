"""Automatic recording of weather values for chosen links (opt-in, OFF by default). Pure scheduling logic; plugin.py runs the fetches.

What it promises, and nothing more:
* off at every QGIS start; the user switches it on in the History window, picks the links (the link shown in the results panel is added
  with "Record this link"), and it stops when QGIS closes or the plugin unloads. Nothing runs between QGIS sessions.
* each recorded link is fetched every ``interval_min`` minutes (default 15, between 15 and 240, as in Velorona Map), in background rounds
  that fetch the due links ONE AT A TIME, with a small random delay so many users do not all ask at the same second;
* at most ``max_links`` links (the free plan's limit, core/entitlements.py);
* per link, as in the Map: a busy source (HTTP 429 or 5xx, or a daily limit) doubles that link's wait, up to 8x the interval, and ends the
  round so nothing more is asked of it now; three failed or busy fetches of a link in a row stop recording of that link (W-RECORD-STOPPED)
  and the values already stored are kept. A failure is never stored as a value;
* only links of public records (a Fixed Service link from a public register) are recorded. The user's own imported links and sites are never
  recorded on a timer (I-RECORD-MYDATA, as in the Map): nothing about them is fetched without the user asking each time;
* values are stored by the same capture as a manual analysis, with the time the provider gives and the real fetch time.
Gaps are normal (the computer sleeps, QGIS is closed): the series is what was fetched, nothing is filled in.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

DEFAULT_INTERVAL_MIN = 15
INTERVAL_CHOICES_MIN = (15, 30, 60, 120, 240)
MAX_INTERVAL_MIN = 240
MAX_BACKOFF_FACTOR = 8
STOP_AFTER_FAILURES = 3
JITTER_S = 60

# Message IDs: all from the Map registry (core/messages.json), same situations, same words.
OFF, ON, LIMIT, BUSY, STOPPED, ADDED, ALREADY, NEEDS_WEATHER, MYDATA = (
    "I-RECORD-OFF", "I-RECORD-ON", "W-RECORD-LIMIT", "W-RECORD-BUSY", "W-RECORD-STOPPED", "I-RECORD-ADDED", "I-RECORD-ALREADY", "I-RECORD-NEEDS-WEATHER",
    "I-RECORD-MYDATA")


@dataclass
class Watched:
    key: tuple                      # core.study_export.study_key of the link
    label: str                      # what the History window shows
    request: Dict[str, Any]         # what the worker needs to fetch again (see plugin.py _record_round)
    last_ok: Optional[float] = None
    last_error: str = ""
    next_due: Optional[float] = None
    backoff: int = 1                # this link's wait factor (doubles on a busy source, up to MAX_BACKOFF_FACTOR)
    failures: int = 0               # failed or busy fetches in a row
    stopped: bool = False           # recording of this link stopped after STOP_AFTER_FAILURES (W-RECORD-STOPPED)


@dataclass
class Recorder:
    max_links: int
    enabled: bool = False
    interval_min: int = DEFAULT_INTERVAL_MIN
    links: Dict[tuple, Watched] = field(default_factory=dict)
    status_id: str = OFF
    rng: Any = field(default_factory=random.Random)

    # -- user actions --------------------------------------------------------------------------------------------------------------------

    def add(self, watched: Watched, now: Optional[float] = None) -> str:
        if watched.key in self.links:
            self.links[watched.key] = watched          # a newer request (e.g. the names box changed) replaces the old one, and restarts it
            watched.next_due = now if self.enabled else None
            return ALREADY
        if len(self.links) >= self.max_links:
            return LIMIT
        self.links[watched.key] = watched
        watched.next_due = now if self.enabled else None
        return ADDED

    def remove(self, key) -> None:
        self.links.pop(key, None)

    def set_interval(self, minutes: int, floor: int = DEFAULT_INTERVAL_MIN) -> None:
        self.interval_min = min(MAX_INTERVAL_MIN, max(floor, int(minutes)))

    def set_enabled(self, on: bool, now: float) -> str:
        self.enabled = bool(on)
        for w in self.links.values():                  # switching on (again) restarts every link at once, stopped ones included
            w.next_due, w.backoff, w.failures, w.stopped = (now if self.enabled else None), 1, 0, False
        self.status_id = ON if self.enabled else OFF
        return self.status_id

    # -- scheduling ----------------------------------------------------------------------------------------------------------------------

    def due_links(self, now: float) -> List[Watched]:
        """The links to fetch now, in a stable order."""
        if not self.enabled:
            return []
        return [w for k, w in sorted(self.links.items(), key=lambda kv: str(kv[0]))
                if not w.stopped and w.next_due is not None and now >= w.next_due]

    def due(self, now: float) -> bool:
        return bool(self.due_links(now))

    def round(self) -> List[Watched]:
        """Every recorded link, in a stable order (for display)."""
        return [self.links[k] for k in sorted(self.links, key=str)]

    def hold(self, links: List[Watched]) -> None:
        """A round has taken these links: they are not due again until their result is in."""
        for w in links:
            w.next_due = None

    def link_done(self, key, now: float, ok: bool, busy: bool = False) -> Optional[str]:
        """One fetch finished. Returns STOPPED when this was the link's third failure in a row, BUSY on a busy source, else None."""
        w = self.links.get(key)
        if w is None:
            return None
        if ok:
            w.failures, w.backoff = 0, 1
        else:
            w.failures += 1
            if busy:
                w.backoff = min(MAX_BACKOFF_FACTOR, w.backoff * 2)
            if w.failures >= STOP_AFTER_FAILURES:
                w.stopped, w.next_due = True, None
                self.status_id = STOPPED
                return STOPPED
        w.next_due = now + self.interval_min * 60 * w.backoff + self.rng.uniform(0, JITTER_S)
        if busy:
            self.status_id = BUSY
            return BUSY
        return None

    def skipped(self, links: List[Watched], now: float) -> None:
        """Links a round did not reach (it ended at a busy source): due again after one interval, not counted as failures."""
        for w in links:
            if w.next_due is None and not w.stopped:
                w.next_due = now + self.interval_min * 60 + self.rng.uniform(0, JITTER_S)

    def round_finished(self) -> str:
        """The status line after a round: STOPPED / BUSY stay visible until a round is clean; otherwise ON."""
        if not self.enabled:
            return self.status_id
        if any(w.stopped for w in self.links.values()):
            self.status_id = STOPPED
        elif any(w.backoff > 1 for w in self.links.values()):
            self.status_id = BUSY
        else:
            self.status_id = ON
        return self.status_id

    def stop(self) -> None:
        """QGIS is closing or the plugin unloads: nothing more runs, nothing is kept for the next session."""
        self.enabled, self.status_id = False, OFF
        self.links.clear()


def is_busy_failure(exc) -> bool:
    """A busy source, as in the Map (W-RECORD-BUSY): HTTP 429 or 5xx, or a daily request limit (core/provider_retry.py wording)."""
    text = str(exc).lower()
    return ("429" in text or "rate-limiting" in text or "daily request limit" in text or "server error" in text
            or any(f"http 5{d}" in text for d in "0123456789"))
