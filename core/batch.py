"""Terrain clearance for MANY Fixed Service links -- the batch core. QGIS-free (the Processing algorithm in core/processing/ only adapts features to it).

There is no second calculation here. Each link goes through exactly the code a single selected link goes through (core/engines/terrestrial.build_link_params +
analyze_link_record), with exactly the values the single-link dialog would pre-fill and the user accept untouched: the record's own highest published frequency
(typed Observed), the record's own antenna heights where the record carries them (Observed), otherwise the 30 m default (Assumed). So a batch row for a link equals
the independent single-link result for that link (tests/test_terrain_batch.py compares them field by field on the shared parity fixtures). What is batch-only:
the row index, the run time, the status of links that were not attempted, and the rule below.

One difference from the single-link flow, on purpose: the dialog always shows a frequency (the record's, else 7 GHz) and the user confirms it; a batch has no confirmation
step, so a record that publishes no usable frequency is NO DATA ("no frequency") unless the caller passes an explicit fallback frequency, which is then typed Assumed.
Nothing is guessed silently for hundreds of links.

Statuses of a row:
  CLEAR / WATCH / AT RISK / CRITICAL   the terrain result, as in the single-link flow (WATCH below a 1.3 clearance ratio is a provisional threshold, not validated)
  NO DATA   a required input is missing or invalid, or elevation data could not be retrieved; the reason is given and nothing is guessed (transient=True when a retry might help)
  ERROR     an unexpected failure for this link; its type and message are given and the batch continues
  NOT RUN   not attempted (over the link limit, or the run was cancelled)
A library that is too old for the corrected clearance convention stops the whole batch (it would be wrong for every link), never row by row.
"""

from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable, List, Optional, Tuple

from .evidence_record import identity_lines
from .presentation import terrain as pterrain
from .presentation.model import AT_RISK, CLEAR, CRITICAL, NO_DATA, WATCH
from .validation import LibraryOutOfDateError, NoDataError

STATUS_ERROR = "ERROR"
STATUS_NOT_RUN = "NOT RUN"
RESULT_STATUSES = (CLEAR, WATCH, AT_RISK, CRITICAL)
ALL_STATUSES = (CLEAR, WATCH, AT_RISK, CRITICAL, NO_DATA, STATUS_ERROR, STATUS_NOT_RUN)

DEFAULT_MAX_LINKS = 100
HARD_MAX_LINKS = 1000
# Each link makes one Open-Meteo elevation request (50 points). The provider rate-limits (HTTP 429 after a few thousand points in a short time -- seen in the
# Map's parity work); a limit keeps one run well inside that. Raise it deliberately, or pass pause_s.


@dataclass(frozen=True)
class BatchLink:
    """One input link: the record's attributes as the layer carries them (never modified), its two endpoints as (lat, lon) in EPSG:4326 (None if unusable), and the
    QGIS feature id for traceability."""
    attrs: dict
    site_a: Optional[Tuple[float, float]]
    site_b: Optional[Tuple[float, float]]
    fid: Optional[int] = None


COLUMNS = [
    "batch_index", "source_fid", "link_id", "authorization_number", "country", "source",
    "status", "reason", "transient",
    "terrain_class", "near_threshold",
    "distance_km", "bearing_deg", "frequency_ghz", "frequency_origin",
    "site_a_height_m", "site_a_height_origin", "site_b_height_m", "site_b_height_origin",
    "first_fresnel_radius_m", "required_clearance_m", "available_clearance_m", "margin_m", "clearance_ratio", "percent_fresnel_clear",
    "critical_distance_from_a_km", "elevation_samples", "elevation_source",
    "error_type",
]


@dataclass
class BatchRow:
    batch_index: int
    source_fid: Optional[int]
    link_id: str
    authorization_number: str
    country: Optional[str]
    source: str
    status: str
    reason: str = ""
    transient: bool = False
    terrain_class: Optional[str] = None
    near_threshold: Optional[bool] = None
    distance_km: Optional[float] = None
    bearing_deg: Optional[float] = None
    frequency_ghz: Optional[float] = None
    frequency_origin: Optional[str] = None
    site_a_height_m: Optional[float] = None
    site_a_height_origin: Optional[str] = None
    site_b_height_m: Optional[float] = None
    site_b_height_origin: Optional[str] = None
    first_fresnel_radius_m: Optional[float] = None
    required_clearance_m: Optional[float] = None
    available_clearance_m: Optional[float] = None
    margin_m: Optional[float] = None
    clearance_ratio: Optional[float] = None          # None when unbounded (see clearance_ratio_text)
    clearance_ratio_text: Optional[str] = None
    percent_fresnel_clear: Optional[float] = None
    critical_distance_from_a_km: Optional[float] = None
    elevation_samples: Optional[int] = None
    elevation_source: Optional[str] = None
    error_type: Optional[str] = None

    def as_dict(self) -> dict:
        return {c: getattr(self, c) for c in COLUMNS}


@dataclass
class BatchResult:
    rows: List[BatchRow]
    started_utc: str
    finished_utc: str
    max_links: int
    fallback_frequency_ghz: Optional[float]
    canceled: bool = False
    notes: List[str] = field(default_factory=list)

    def counts(self) -> dict:
        out = {s: 0 for s in ALL_STATUSES}
        for r in self.rows:
            out[r.status] = out.get(r.status, 0) + 1
        return out


def _id_of(attrs: dict, index: int) -> Tuple[str, str]:
    link_id = attrs.get("id")
    auth = attrs.get("authorization_number") or link_id
    return (str(link_id) if link_id not in (None, "") else f"row-{index}"), (str(auth) if auth not in (None, "") else f"row-{index}")


def _base_row(index: int, link: BatchLink, status: str, reason: str = "", **extra) -> BatchRow:
    link_id, auth = _id_of(link.attrs, index)
    return BatchRow(batch_index=index, source_fid=link.fid, link_id=link_id, authorization_number=auth, country=link.attrs.get("country") or None,
                    source=str(link.attrs.get("source") or ""), status=status, reason=reason, **extra)


def _row_from_result(index: int, link: BatchLink, res) -> BatchRow:
    r = res.result
    status, reason, _plain = pterrain.terrain_status(r)
    crit = pterrain.critical_point(r)
    ratio = r.clearance_ratio
    unbounded = ratio != ratio or ratio in (float("inf"), float("-inf"))
    height_origins = getattr(res, "height_origins", None) or {}
    freq_origin = getattr(res, "frequency_origin", None)
    return _base_row(
        index, link, status, reason, terrain_class=r.los_status, near_threshold=bool(r.near_threshold),
        distance_km=r.distance_km, bearing_deg=r.bearing_deg, frequency_ghz=r.frequency_ghz,
        frequency_origin=(freq_origin[0] if freq_origin else None),
        site_a_height_m=res.site_a_height_m, site_a_height_origin=(height_origins.get("a") or (None,))[0],
        site_b_height_m=res.site_b_height_m, site_b_height_origin=(height_origins.get("b") or (None,))[0],
        first_fresnel_radius_m=r.first_fresnel_radius_m, required_clearance_m=r.required_clearance_m, available_clearance_m=r.terrain_clearance_m,
        margin_m=r.terrain_clearance_m - r.required_clearance_m, clearance_ratio=None if unbounded else ratio,
        clearance_ratio_text=pterrain.ratio_value(r), percent_fresnel_clear=r.percent_fresnel_clear,
        critical_distance_from_a_km=crit.distance_from_a_km if crit is not None else None,
        elevation_samples=len(r.profile), elevation_source=pterrain.ELEVATION_SOURCE)


def _defaults(engine=None):
    if engine is None:
        from .engines import terrestrial as engine
    return engine.build_link_params, engine.analyze_link_record


def analyze_one(index: int, link: BatchLink, *, fallback_frequency_ghz: Optional[float] = None, build_params: Callable = None, analyze: Callable = None) -> BatchRow:
    """One link, as the single-link flow would run it. Never raises for a per-link problem (see the module docstring); a library-too-old error propagates."""
    if build_params is None or analyze is None:
        bp, an = _defaults()
        build_params, analyze = build_params or bp, analyze or an
    if link.site_a is None or link.site_b is None:
        return _base_row(index, link, NO_DATA, "The link record has no usable endpoint geometry.")
    try:
        params, record_ghz, note = build_params(link.attrs)
        if record_ghz is None:
            if fallback_frequency_ghz is None:
                return _base_row(index, link, NO_DATA, f"The record publishes no usable frequency ({note}) and no fallback frequency was given; none is assumed in a batch.")
            params = {**params, "frequency_ghz": float(fallback_frequency_ghz)}
        res = analyze(link.attrs, link.site_a, link.site_b, params)
        return _row_from_result(index, link, res)
    except LibraryOutOfDateError:
        raise
    except NoDataError as exc:
        return _base_row(index, link, NO_DATA, "; ".join(exc.reasons), transient=bool(exc.transient))
    except Exception as exc:   # an unexpected failure for THIS link: reported with its type, the batch continues
        return _base_row(index, link, STATUS_ERROR, f"{exc}", error_type=type(exc).__name__)


def run_batch(links: Iterable[BatchLink], *, fallback_frequency_ghz: Optional[float] = None, max_links: int = DEFAULT_MAX_LINKS,
              build_params: Callable = None, analyze: Callable = None, progress: Optional[Callable[[int, int, BatchRow], None]] = None,
              is_canceled: Optional[Callable[[], bool]] = None, pause_s: float = 0.0, sleep: Callable[[float], None] = time.sleep) -> BatchResult:
    """Runs every link (up to ``max_links``); the rest are reported NOT RUN, never silently dropped. The input links and their attributes are not modified."""
    links = list(links)
    if not isinstance(max_links, int) or isinstance(max_links, bool) or not 1 <= max_links <= HARD_MAX_LINKS:
        raise ValueError(f"max_links must be a whole number from 1 to {HARD_MAX_LINKS}.")
    if fallback_frequency_ghz is not None and not (isinstance(fallback_frequency_ghz, (int, float)) and 0.1 <= fallback_frequency_ghz <= 100):
        raise ValueError("The fallback frequency must be between 0.1 and 100 GHz.")
    if build_params is None or analyze is None:
        bp, an = _defaults()
        build_params, analyze = build_params or bp, analyze or an
    started = datetime.now(timezone.utc).isoformat()
    rows: List[BatchRow] = []
    canceled = False
    total = len(links)
    for index, link in enumerate(links):
        if canceled or (is_canceled is not None and is_canceled()):
            canceled = True
            rows.append(_base_row(index, link, STATUS_NOT_RUN, "The run was cancelled before this link."))
        elif index >= max_links:
            rows.append(_base_row(index, link, STATUS_NOT_RUN, f"Over the limit of {max_links} links for one run; raise the limit or run the rest separately."))
        else:
            if pause_s and index:
                sleep(pause_s)
            rows.append(analyze_one(index, link, fallback_frequency_ghz=fallback_frequency_ghz, build_params=build_params, analyze=analyze))
        if progress is not None:
            progress(index + 1, total, rows[-1])
    return BatchResult(rows=rows, started_utc=started, finished_utc=datetime.now(timezone.utc).isoformat(), max_links=max_links,
                       fallback_frequency_ghz=fallback_frequency_ghz, canceled=canceled)


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)           # shortest round-trip: precision belongs to whoever produced the number
    return value


def batch_to_csv(batch: BatchResult) -> str:
    """The batch as a CSV: a '# ' preamble (product, libraries, convention, what a row means, counts), then one row per link with the columns above."""
    counts = batch.counts()
    lines = [
        "Velorona QGIS -- Terrain clearance, batch export (one row per link)",
        "Each row is the same calculation as selecting that link and running Terrestrial Path Clearance with the dialog's pre-filled values: the record's own highest published "
        "frequency (Observed) and the record's own antenna heights where it carries them (Observed), otherwise 30 m (Assumed).",
        ("A record that publishes no usable frequency is NO DATA in a batch" + (f", unless the fallback frequency {batch.fallback_frequency_ghz:g} GHz (Assumed) was given." if batch.fallback_frequency_ghz is not None else
                                                                               " (no fallback frequency was given; none is assumed).")),
        "Status: CLEAR/WATCH/AT RISK/CRITICAL = terrain result (WATCH = clearance ratio below a provisional 1.3, not validated); NO DATA = a required input is missing or invalid, "
        "or elevation data was unavailable (reason given; nothing guessed); ERROR = unexpected failure for that link (type and message given); NOT RUN = not attempted (limit or cancel).",
        "Geometry and DEM only: a 90 m surface model that may include canopy and rooftops. Not an outage prediction and not a field measurement.",
        *identity_lines(decision=True),
        f"Batch: {len(batch.rows)} link(s); " + ", ".join(f"{s} {counts[s]}" for s in ALL_STATUSES if counts[s]) + (" -- run cancelled" if batch.canceled else ""),
        f"Limit per run: {batch.max_links}. Started {batch.started_utc}; finished {batch.finished_utc}.",
    ]
    buf = io.StringIO()
    buf.write("".join(f"# {ln}\n" for ln in lines) + "#\n")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(COLUMNS)
    for r in batch.rows:
        d = r.as_dict()
        if d["clearance_ratio"] is None and r.clearance_ratio_text == "unbounded":
            d["clearance_ratio"] = "unbounded"
        writer.writerow([_cell(d[c]) for c in COLUMNS])
    return buf.getvalue()
