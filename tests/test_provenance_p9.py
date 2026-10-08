"""Provenance contract (owner-approved P9): Observed / Model-derived / Calculated / Inferred / Assumed. User-entered values are NEVER Observed.
R6 (radar classification) is not decided and is not asserted here."""
import csv
import io
from types import SimpleNamespace

import pytest

from core.export import result_to_csv
from presentation_fixtures import terrain_result, weather_result

VOCAB = {"Observed", "Model-derived", "Calculated", "Inferred", "Assumed"}


def rows(res):
    body = "".join(l for l in io.StringIO(result_to_csv(res)) if not l.startswith("#"))
    return {r[0]: r for r in list(csv.reader(io.StringIO(body)))[1:]}


def test_terrain_user_entered_values_are_assumed_feature_attributes_are_observed():
    res = terrain_result()                       # site A height entered by the user, site B height from the feature's own attribute
    r = rows(res)
    assert r["Site A antenna height"][1] == "Assumed" and r["Site B antenna height"][1] == "Observed"
    assert r["Frequency"][1] == "Assumed" and "user-provided" in r["Frequency"][5].lower()
    assert r["Ground elevation profile"][1] == "Observed"
    assert {x[1] for x in r.values()} <= VOCAB


def test_two_site_weather_user_parameters_are_assumed_and_model_values_are_model_derived():
    r = rows(weather_result())
    for name in ("Fade margin (link spec)", "Frequency / polarization"):
        assert r[name][1] == "Assumed", name
    assert r["Rain rate used"][1] == "Model-derived"
    assert all(v[1] == "Model-derived" for k, v in r.items() if k.startswith("Model precipitation"))
    assert {x[1] for x in r.values()} <= VOCAB


def _investigation(origins):
    res = weather_result()
    return SimpleNamespace(kind="link-investigation", exposure=res, param_origins=origins, weather_error=None,
                           entry=SimpleNamespace(data={"authorization_number": "X-1", "source": "ISED", "frequencies_mhz": [18000.0]},
                                                 site_a_point=(43.7, -79.4), site_b_point=(43.8, -79.2)))


def test_link_record_row_types_follow_the_parameter_origins():
    r = rows(_investigation({"frequency_ghz": ("Observed", "record"), "polarization": ("Assumed", "engine default"), "fade_margin_db": ("Assumed", "engine default")}))
    assert r["Frequency used for attenuation"][1] == "Observed"             # the record's own value
    assert r["Polarization"][1] == "Assumed" and r["Fade margin"][1] == "Assumed"


def test_missing_origins_default_to_assumed_never_observed():
    r = rows(_investigation({}))
    assert {r[k][1] for k in ("Frequency used for attenuation", "Polarization", "Fade margin")} == {"Assumed"}


def test_user_overridden_record_frequency_is_assumed():
    r = rows(_investigation({"frequency_ghz": ("Assumed", "user override"), "polarization": ("Assumed", ""), "fade_margin_db": ("Assumed", "")}))
    assert r["Frequency used for attenuation"][1] == "Assumed"
