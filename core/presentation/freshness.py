"""One freshness line per model weather number: ``source · kind · as of <time> (<zone>), fetched <HH:MM UTC>`` (UI_AUDIT section 3).

Open-Meteo is asked with ``timezone=auto``, so ``current.time`` is the SITE's local time, not UTC. It is therefore never labelled UTC here:
the line says it is the provider's own time for the site. The fetch time is ours (a Unix time) and is shown in UTC. Pure Python."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def fetched_utc(fetched_at: Optional[float]) -> str:
    if fetched_at is None:
        return "fetch time not recorded"
    return "fetched " + datetime.fromtimestamp(float(fetched_at), timezone.utc).strftime("%H:%M UTC")


def model_line(observation) -> str:
    """The freshness line for a model-derived weather observation (``WeatherObservation``-like: source, timestamp, fetched_at)."""
    ts = str(getattr(observation, "timestamp", "") or "").replace("T", " ") or "time not reported"
    source = str(getattr(observation, "source", "") or "Open-Meteo")
    return f"{source} · model-derived · as of {ts} (site local time, as reported by the provider), {fetched_utc(getattr(observation, 'fetched_at', None))}"


def for_site(representativeness, site_id) -> str:
    """The line for the observation behind ``site_id`` in a result's ``representativeness`` map, or a statement that none is available."""
    rep = (representativeness or {}).get(site_id)
    obs = getattr(rep, "model_observation", None)
    return model_line(obs) if obs is not None else "no model observation time available for this value"
