"""ONE place that turns app data into model features. Remap here when the CV Engineer's feature mapping lands.

Model features are EXPOSURE-NORMALISED so CSV athlete logs (gps_distance, minutes_played, heart_rate, sprints,
top_speed) and calibrated CV rows (normalised by visible_minutes) land on the same scale. See ml/README.md.
Never used as features: injury_risk / fatigue_risk_score (ingest defaults), high_intensity_efforts (double counts
hsr+sprint), accels/decels (not reliably produced by the CV; display only).
"""
from typing import Iterable, Mapping, Optional

FEATURES = [
    "acwr",                # acute:chronic ratio of session load (this session / mean of previous <= 4)
    "distance_m_per_min",  # distance / exposure minutes (m/min)
    "sprints_per_90",      # sprint_count / exposure minutes * 90
    "hsr_m_per_min",       # high-speed running distance / exposure minutes (m/min); CSV usually lacks it
    "top_speed_kmh",       # peak speed (km/h)
    "minutes_played",      # time on the pitch (CSV / demo only; NEVER CV visible_minutes)
    "heart_rate_avg",      # average heart rate (bpm), CSV only
    "hr_missing",          # 1 = no heart rate (HR then imputed with the training median)
]

LABELS = {
    "acwr": "Acute:chronic workload ratio",
    "distance_m_per_min": "Distance per minute (m/min)",
    "sprints_per_90": "Sprints per 90 min",
    "hsr_m_per_min": "High-speed running per minute (m/min)",
    "top_speed_kmh": "Top speed (km/h)",
    "minutes_played": "Minutes played",
    "heart_rate_avg": "Average heart rate (bpm)",
    "hr_missing": "Heart rate not provided",
}

# API display features (contract): raw, un-normalised values, all nullable
DISPLAY_FEATURES = ["distance_km", "sprint_count", "minutes_played", "top_speed_kmh", "hsr_distance_km",
                    "accels", "decels", "heart_rate_avg", "heart_rate_max"]

ACWR_CHRONIC_WINDOW = 4
MIN_EXPOSURE_MIN = 1.0
MPH_TO_KMH = 1.609344


def f(v) -> Optional[float]:
    if v is None or isinstance(v, bool) or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def ratio(current: Optional[float], prior: Iterable[Optional[float]]) -> Optional[float]:
    """current / mean(previous <= 4 values, most recent last). None without usable history."""
    hist = [x for x in (f(v) for v in prior) if x is not None and x > 0][-ACWR_CHRONIC_WINDOW:]
    if current is None or not hist:
        return None
    return round(min(current / (sum(hist) / len(hist)), 5.0), 3)


def _per_min(v: Optional[float], minutes: Optional[float], scale: float = 1.0) -> Optional[float]:
    if v is None or minutes is None or minutes < MIN_EXPOSURE_MIN:
        return None
    return round(v * scale / minutes, 4)


def stat_values(values: Mapping) -> dict:
    """Normalise one player_match_stats row ({column-or-metric-key: value}) to the names used below."""
    dist = f(values.get("distance_km"))
    if dist is None and f(values.get("distance_covered_meters")) is not None:
        dist = f(values.get("distance_covered_meters")) / 1000.0
    kmh = f(values.get("top_speed_kmh"))
    if kmh is None and f(values.get("top_speed_mph")) is not None:
        kmh = round(f(values.get("top_speed_mph")) * MPH_TO_KMH, 2)
    return {"distance_km": dist, "sprint_count": f(values.get("sprint_count")),  # never high_intensity_efforts
            "minutes_played": f(values.get("minutes_played")), "visible_minutes": f(values.get("visible_minutes")),
            "top_speed_kmh": kmh, "hsr_distance_km": f(values.get("hsr_distance_km")),
            "accels": f(values.get("accels")), "decels": f(values.get("decels"))}


def match_load(v: Mapping, exposure_min: Optional[float]) -> Optional[float]:
    """CV/demo session load for ACWR = distance rate (clips are partial, so totals are not comparable)."""
    return _per_min(v.get("distance_km"), exposure_min, 1000.0)


def match_features(v: Mapping, exposure_min: Optional[float], prior_loads: Iterable[Optional[float]],
                   heart_rate: Optional[float], minutes_played: Optional[float]) -> dict:
    """v = stat_values(). exposure_min = visible_minutes (real CV) or minutes (demo). minutes_played = None for
    real CV rows (visible_minutes is exposure, not time on the pitch)."""
    load = match_load(v, exposure_min)
    return _model_row(acwr=ratio(load, prior_loads), dist_rate=load,
                      sprints90=_per_min(v.get("sprint_count"), exposure_min, 90.0),
                      hsr_rate=_per_min(v.get("hsr_distance_km"), exposure_min, 1000.0),
                      top=v.get("top_speed_kmh"), minutes=minutes_played, hr=heart_rate)


def csv_load(log: Mapping) -> Optional[float]:
    """CSV session load for ACWR = total GPS distance (km): whole sessions, so totals are comparable."""
    return f(log.get("gps_distance_km"))


def csv_features(log: Mapping, prior_loads: Iterable[Optional[float]]) -> dict:
    """log = {gps_distance_km, minutes_played, heart_rate, sprints, top_speed_kmh} (one athlete-log row)."""
    mins = f(log.get("minutes_played"))
    return _model_row(acwr=ratio(csv_load(log), prior_loads),
                      dist_rate=_per_min(f(log.get("gps_distance_km")), mins, 1000.0),
                      sprints90=_per_min(f(log.get("sprints")), mins, 90.0), hsr_rate=None,
                      top=f(log.get("top_speed_kmh")), minutes=mins, hr=f(log.get("heart_rate")))


def _model_row(acwr, dist_rate, sprints90, hsr_rate, top, minutes, hr) -> dict:
    return {"acwr": acwr, "distance_m_per_min": dist_rate, "sprints_per_90": sprints90,
            "hsr_m_per_min": hsr_rate, "top_speed_kmh": top, "minutes_played": minutes,
            "heart_rate_avg": hr, "hr_missing": 0.0 if hr is not None else 1.0}


def display_from_stat(v: Mapping, hr_avg=None, hr_max=None) -> dict:
    return {"distance_km": v.get("distance_km"), "sprint_count": v.get("sprint_count"),
            "minutes_played": v.get("minutes_played"), "top_speed_kmh": v.get("top_speed_kmh"),
            "hsr_distance_km": v.get("hsr_distance_km"), "accels": v.get("accels"), "decels": v.get("decels"),
            "heart_rate_avg": f(hr_avg), "heart_rate_max": f(hr_max)}


def display_from_log(log: Mapping) -> dict:
    return {"distance_km": f(log.get("gps_distance_km")), "sprint_count": f(log.get("sprints")),
            "minutes_played": f(log.get("minutes_played")), "top_speed_kmh": f(log.get("top_speed_kmh")),
            "hsr_distance_km": None, "accels": None, "decels": None,
            "heart_rate_avg": f(log.get("heart_rate")), "heart_rate_max": f(log.get("heart_rate_max"))}
