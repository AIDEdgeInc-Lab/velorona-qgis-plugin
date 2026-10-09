"""QGIS attribute schemas for the USA layers. Kept apart from ``usa.py`` so the provider stays importable (and testable) without QGIS."""

from __future__ import annotations

from qgis.PyQt.QtCore import QVariant

from ..sources.terrestrial_public import FIXED_LINK_FIELDS, FIXED_SITE_FIELDS

# The Canadian fields first, unchanged (so the same table/drawer code reads them), then what a US record adds. `attribution`,
# `pack_generated` and `source_file_updated` travel with every feature so a selection, a table row or an export can state its source.
US_SITE_FIELDS = FIXED_SITE_FIELDS + [
    ("country", QVariant.String), ("flags", QVariant.String),
    ("attribution", QVariant.String), ("pack_generated", QVariant.String), ("source_file_updated", QVariant.String),
    ("pack_input_sha256", QVariant.String),
]

US_LINK_FIELDS = FIXED_LINK_FIELDS + [
    ("country", QVariant.String), ("call_sign", QVariant.String), ("path_type", QVariant.String),
    ("grant_date", QVariant.String), ("expiration_date", QVariant.String), ("flags", QVariant.String),
    ("attribution", QVariant.String), ("pack_generated", QVariant.String), ("source_file_updated", QVariant.String),
    ("pack_input_sha256", QVariant.String),
    ("site_a_height_m", QVariant.Double), ("site_b_height_m", QVariant.Double), ("height_source", QVariant.String),
]

# Optional record antenna heights on Canadian link layers (only when a heights sidecar is present; see core/countries/canada.py).
CA_HEIGHT_FIELDS = [("site_a_height_m", QVariant.Double), ("site_b_height_m", QVariant.Double), ("height_source", QVariant.String)]
