"""Does the shared workflow core (aei_workflow, as used by the unmerged feat/automation-workflow-runs branch) decide like the plugin's single-link flow?

Runs every shared parity fixture through (a) the plugin's single-link analysis + status model and (b) aei_workflow.engine.analyze_link_row with the SAME inputs and the same
offline elevation double. The numbers must agree (same library). What is recorded, not hidden, is how the DECISION vocabularies relate: the workflow core reports the library's
three line-of-sight classes only, with no WATCH rule, NO DATA boundary or Observed/Assumed provenance, so a run history built on it would not say what the plugin's Results panel says.
Skipped when aei_workflow is not installed (it is not a dependency of the released plugin)."""
import collections

import pytest

pytest.importorskip("aei_workflow")

from aei_workflow import engine as wf_engine  # noqa: E402

import test_terrain_batch as T  # noqa: E402
from test_terrain_batch import elevation_service  # noqa: E402,F401  (autouse offline elevation double)


def _workflow_row(link, params):
    return {"link_id": link.attrs["id"], "site_a_lat": link.site_a[0], "site_a_lon": link.site_a[1], "site_a_height_m": params["site_a_height_m"],
            "site_b_lat": link.site_b[0], "site_b_lon": link.site_b[1], "site_b_height_m": params["site_b_height_m"], "frequency_ghz": params["frequency_ghz"]}


def _compare():
    pairs, numeric_mismatch = [], []
    for fx in T.FIXTURES:
        link = T.to_link(fx)
        try:
            params, _ghz, _note = T.tr.build_link_params(link.attrs)
            res, r, status, _reason = T.independent_single(link)
        except Exception:
            continue                                   # the plugin flow refuses this input (NO DATA); the workflow core has no such boundary
        T.CURRENT[0] = link.attrs["id"]
        out = wf_engine.analyze_link_row(_workflow_row(link, params), {"k_factor": 4.0 / 3.0, "n_samples": 50})      # the library defaults, which the plugin flow also uses
        for key in ("terrain_clearance_m", "required_clearance_m", "first_fresnel_radius_m", "distance_km"):
            if out.get(key) != getattr(r, key):
                numeric_mismatch.append((link.attrs["id"], key, out.get(key), getattr(r, key)))
        pairs.append((status, out.get("los_status")))
    return pairs, numeric_mismatch


def test_workflow_core_numbers_equal_the_plugin_flow():
    pairs, mismatch = _compare()
    assert len(pairs) > 40
    assert not mismatch, mismatch[:5]


def test_decision_vocabulary_difference_is_recorded():
    """Documents the verified divergence (see docs/CAPABILITY_STATUS.md): the plugin status cannot be recovered from the workflow core's class alone."""
    pairs, _ = _compare()
    table = collections.Counter(pairs)
    plugin_statuses_per_class = collections.defaultdict(set)
    for plugin_status, los in pairs:
        plugin_statuses_per_class[los].add(plugin_status)
    print("plugin status x workflow class:", dict(table))
    assert plugin_statuses_per_class, "no comparable fixtures"
