"""Where a link record came from, and what that means for provenance. Pure stdlib -- runs without QGIS.

One place for the rules that must be identical for every country's records:

* the highest published frequency on a record is the frequency used (rain attenuation rises with frequency; CARRIED OVER from 1.1.4, and
  the Velorona Map's ``frequencyGhzFromRecord``);
* a value is **Observed** only if it is the record's own; a value the user typed or changed is **Assumed** (spec F.1, owner-approved P9);
* wording that names the register (ISED / FCC ULS) follows the record's own source -- Canadian text is unchanged.

``frequency_origin`` is the "frequency-origin channel": the terrain flow used to type the frequency Assumed because it never knew whether the
number came from a record. It now receives the record's value and the value actually used, and decides from those two.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

# Two frequencies are "the same value" when they agree to well below anything the dialog can express (it shows 1-3 decimals of GHz).
SAME_GHZ_TOLERANCE = 1e-9


def frequency_ghz_from_record(frequencies_mhz) -> Tuple[Optional[float], str]:
    """(GHz, provenance note) from a record's published frequency list (comma separated MHz), or (None, reason). The highest published
    frequency on the authorization is used: rain attenuation rises with frequency, so it is the conservative choice, and it is a value
    from the record -- never invented."""
    if not frequencies_mhz:
        return None, "No frequency published on this authorization."
    values = []
    for chunk in str(frequencies_mhz).split(","):
        try:
            value = float(chunk.strip())
        except ValueError:
            continue
        if math.isfinite(value):
            values.append(value)
    if not values:
        return None, "Published frequency could not be parsed from this record."
    top = max(values)
    note = (f"Highest of {len(values)} published frequencies on this authorization "
            f"({top:.1f} MHz); rain attenuation rises with frequency.")
    return top / 1000.0, note


@dataclass(frozen=True)
class RecordLabels:
    code: str                 # "ISED" | "FCC"
    record_prefix: str        # prefix of the Source text for a record-sourced value (Map: "ISED record" / "FCC ULS record")
    extract: str              # how the source register is named in sentences
    authorization: str        # how one record is named
    interpretation_register: str


_ISED = RecordLabels("ISED", "ISED record", "ISED Fixed Service extract", "ISED Fixed Service authorization", "ISED's Fixed Service extract")
_FCC = RecordLabels("FCC", "FCC ULS record", "FCC ULS microwave records (l_micro)", "FCC ULS licence", "the FCC ULS microwave records")


def is_fcc(attrs) -> bool:
    attrs = attrs or {}
    return str(attrs.get("country") or "").upper() == "US" or "FCC" in str(attrs.get("source") or "")


def record_labels(attrs) -> RecordLabels:
    return _FCC if is_fcc(attrs) else _ISED


def frequency_origin(record_ghz: Optional[float], record_note: str, used_ghz: float, labels: RecordLabels = _ISED) -> Tuple[str, str]:
    """('Observed' | 'Assumed', note) for the frequency actually used in an analysis.

    * no record value (analysis not bound to a record, or the record publishes none) -> Assumed
    * used == the record's own value                                             -> Observed (it IS the record's value)
    * used differs (the user overrode it)                                        -> Assumed, and the note says what the record said
    """
    if record_ghz is None:
        return "Assumed", "User, via analysis dialog (not sourced from license data)"
    if abs(float(used_ghz) - float(record_ghz)) <= SAME_GHZ_TOLERANCE:
        return "Observed", f"{labels.record_prefix} -- {record_note}"
    return ("Assumed",
            f"User override via analysis dialog: the {labels.record_prefix}'s own value is {record_ghz:g} GHz ({record_note}); "
            f"{used_ghz:g} GHz was entered instead.")


# The label the Velorona Map contract (parity/contract/USA_PACK_SCHEMA.md section 3.3) prescribes for an FCC antenna height: the only
# correct description of what the field is. Used when a US record carries a height and gives no source text of its own.
FCC_HEIGHT_LABEL = ("antenna height to centre (FCC field 'Height to Center RAAT'), licensee-reported record value, metres, interpreted "
                    "as above ground; not a field measurement")


def height_origin(record_m: Optional[float], used_m: float, record_source: str = "") -> Tuple[str, str]:
    """('Observed' | 'Assumed', source text) for an antenna height actually used in an analysis.

    Same rule as the frequency (spec F.2: "antenna height Observed only if the record carries it, else Assumed"; F.1: overridden by the user it
    becomes Assumed). A record that carries no height leaves the engine default, which is Assumed."""
    if record_m is None:
        return "Assumed", "User, via analysis dialog (default shown, user-confirmed)"
    if abs(float(used_m) - float(record_m)) <= SAME_GHZ_TOLERANCE:      # the tolerance is far below a centimetre in either unit
        return "Observed", record_source or "Record"
    return "Assumed", f"User override via analysis dialog: the record's own value is {record_m:g} m ({record_source or 'record'}); {used_m:g} m was entered instead."
