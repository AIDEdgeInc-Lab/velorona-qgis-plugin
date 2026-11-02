"""Every model weather number carries source + time + unit (UI_AUDIT F3). Open-Meteo's time is the SITE's local time, so it is never called UTC."""
import csv
import io
from types import SimpleNamespace

from core.export import result_to_csv
from core.presentation import freshness
from presentation_fixtures import weather_result


def test_model_line_names_source_kind_time_and_fetch_time():
    o = SimpleNamespace(source="Open-Meteo", timestamp="2026-10-06T20:00", fetched_at=1790000000.0)
    line = freshness.model_line(o)
    assert line.startswith("Open-Meteo · model-derived · as of 2026-10-06 20:00 (site local time, as reported by the provider), fetched ")
    assert line.endswith(" UTC")


def test_missing_fetch_time_is_stated_not_invented():
    line = freshness.model_line(SimpleNamespace(source="Open-Meteo", timestamp="2026-10-06T20:00", fetched_at=None))
    assert "fetch time not recorded" in line


def test_no_observation_is_stated():
    assert "no model observation time" in freshness.for_site({}, "A")


def test_the_weather_export_rain_rate_row_carries_the_time_and_unit():
    res = weather_result()
    rows = [r for r in csv.reader(io.StringIO("".join(l for l in io.StringIO(result_to_csv(res)) if not l.startswith("#"))))]
    for label in ("Rain rate used", "Model precipitation (Site A)"):
        row = next(r for r in rows if r and r[0].startswith(label))
        assert "mm/h" in row[3] and "as of 2026-10-06 20:00" in row[3] and "model-derived" in row[3], row
        assert "open-meteo" in (row[2] + row[3]).lower()
