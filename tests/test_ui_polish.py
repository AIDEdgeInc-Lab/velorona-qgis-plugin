"""Link title, NO DATA wording and baseline grouping (pure Python; the scale/Records checks are in qgis_ui_polish_e2e.py)."""
import pytest
from presentation_fixtures import terrain_result, weather_result

from core.presentation import terrain as T
from core.presentation import weather as W
from core.presentation.model import link_title


@pytest.mark.parametrize("value,expected", [
    ("010029391-004", "010029391-004 · Site A ↔ Site B"),
    (None, "Site A ↔ Site B"), ("", "Site A ↔ Site B"), ("link", "Site A ↔ Site B"),
])
def test_link_title(value, expected):
    assert link_title(value) == expected


def test_briefs_carry_a_heading_and_keep_the_exported_location():
    w = W.exposure_brief(weather_result())
    t = T.terrain_brief(terrain_result())
    assert "↔" in w.heading and w.location == "Site A ↔ Site B"
    assert t.heading == "Site A \u2194 Site B" and t.location == "Site A \u2192 Site B"  # no authorization in fixture; export text unchanged
    r = terrain_result()
    r.record = {"authorization_number": "010029391-004"}
    assert T.terrain_brief(r).heading.startswith("010029391-004 \u00b7 ")
