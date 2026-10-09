"""Country data providers: shared error types and the record vocabulary every provider returns. Pure stdlib -- runs without QGIS.

A provider turns one country's public link records into the plugin's existing record dicts (the shape ``terrestrial_public`` already
returns for Canada). It owns loading, validation and attribution; it does NOT analyse anything. Analysis is country-agnostic
(core/engines), so a provider never imports an engine and no engine imports a provider.

Errors here are deliberately NOT NoDataError: a missing, corrupt or incompatible pack is a data-source problem the user must be told
about, never a per-link "NO DATA" decision (owner rule: NO DATA only through explicit validation at the analysis boundary).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


class PackError(Exception):
    """A country data pack could not be used. ``str(exc)`` is a complete, user-facing sentence."""


class PackNotConfiguredError(PackError):
    """No pack source has been set."""


class PackMissingError(PackError):
    """The pack (or a file the pack's index lists) does not exist at the configured source."""


class PackUnavailableError(PackError):
    """The pack source could not be reached (network error, timeout, HTTP 5xx). Retrying later may work."""


class PackCorruptError(PackError):
    """A pack file exists but is not valid (bad gzip/JSON, wrong structure, impossible values, over the size guard)."""


class PackVersionError(PackError):
    """The pack's schema is not one this plugin version understands."""


class ViewTooLargeError(PackError):
    """The requested extent would load more records than the in-project budget allows; the user should zoom in."""


@dataclass(frozen=True)
class Attribution:
    """What must travel with a country's results (UI, layer abstract, exports)."""
    country: str
    source_name: str               # e.g. "U.S. Federal Communications Commission, Universal Licensing System (ULS) ..."
    attribution_text: str          # the pack's own attribution string, verbatim
    source_file_updated: str       # date of the source file (YYYY-MM-DD)
    pack_generated: str            # date the pack was built from it (YYYY-MM-DD)
    nature: str = ("Licensee-reported record data from a public register; not a field measurement and not a "
                   "coverage or performance guarantee.")

    def one_line(self) -> str:
        return (f"{self.attribution_text} Source file dated {self.source_file_updated}; pack built {self.pack_generated}. "
                f"{self.nature}")


@dataclass
class LoadResult:
    sites: List[dict] = field(default_factory=list)
    links: List[dict] = field(default_factory=list)
    attribution: Optional[Attribution] = None
    tiles_requested: int = 0
    tiles_fetched: int = 0                 # not served from the in-memory cache
    duplicate_links_dropped: int = 0       # same link id seen again in a neighbouring tile
    duplicate_sites_dropped: int = 0
    heights_error: str = ""               # an optional heights file was present but unusable: why (the records still load, with the default heights)
    heights_attached: int = 0              # links that received record antenna heights (0 = none: the 30 m default / user value applies)
