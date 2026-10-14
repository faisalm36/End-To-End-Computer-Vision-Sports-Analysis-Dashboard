"""Per-player metric registry + helpers (design: docs/metrics-extension-plan.md, option B).

- DEFINITIONS is the single source of truth. migrations/004 + schema.sql seed the same rows (a test checks they
  match), and ensure_definitions() upserts them at startup / in seed.py.
- distance_km / top_speed_mph stay real columns on player_match_stats (storage='column'); every other metric is a
  row in player_match_metrics (storage='metric'), one per player per video.
- PIPELINE_ALIASES maps CV pipeline output keys -> our metric keys (e.g. high_speed_distance_km -> hsr_distance_km).
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Iterable, Optional

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

log = logging.getLogger("metrics")

GRID_COLS, GRID_ROWS = 12, 8          # heatmap grid: 12 along the pitch length (x), 8 across the width (y)
DEFAULT_PITCH = (105.0, 68.0)         # length_m, width_m (cv/config/default_calibration.json)
# Rates per minute (distance_per_min) are null below this many minutes: on very short clips / brief appearances the
# ratio is noise (e.g. 7 km / 1 s = 438,000 m/min) and dividing by ~0 must never happen.
MIN_RATE_MINUTES = 0.1
# Speed thresholds the CV pipeline writes to meta.json (cv/config.py, preset gps_standard: HIGH_SPEED 12.3 mph,
# SPRINT 15.7 mph; meta rounds the km/h values to 1 dp: 19.8 / 25.3; PR #2 derives the run/hsr zone edges from
# them). Used by the API when a video's pipeline_meta has none (seeded rows, older pipelines).
DEFAULT_SPEED_THRESHOLDS = {"preset": "gps_standard", "hsr_kmh": 19.8, "sprint_kmh": 25.3,
                            "zone_edges_kmh": {"walk": 7.0, "jog": 15.0, "run": 19.8, "hsr": 25.3}}

_F = ("metric_key", "label", "unit", "category", "value_type", "aggregation", "ratio_numerator",
      "ratio_denominator", "ratio_scale", "decimals", "higher_is_better", "requires_calibration", "is_estimate",
      "availability", "storage", "sort_order", "description")


def _d(*vals) -> dict:
    return dict(zip(_F, vals))


# key, label, unit, category, value_type, aggregation, ratio_num, ratio_den, ratio_scale, decimals,
# higher_is_better, requires_calibration, is_estimate, availability, storage, sort_order, description
DEFINITIONS: list[dict] = [
    # ---- physical / coverage / positional ----
    _d("distance_km", "Total distance", "km", "physical", "float", "sum", None, None, 1.0, 2, True, True, True,
       "ready", "column", 10, "Distance covered while tracked (smoothed). Estimated from video."),
    _d("top_speed_mph", "Top speed (max sustained)", "mph", "physical", "float", "max", None, None, 1.0, 1, True,
       True, True, "ready", "column", 11, "Max sustained (~1 s rolling) speed. Estimated from video."),
    _d("top_speed_kmh", "Top speed (max sustained)", "km/h", "physical", "float", "max", None, None, 1.0, 1, True,
       True, True, "ready", "metric", 12, "Same as top_speed_mph in km/h (pipeline top_speed_kmh, else mph x 1.60934)."),
    _d("distance_per_min", "Distance per minute", "m/min", "physical", "float", "ratio", "distance_km",
       "visible_minutes|minutes_played", 1000.0, 0, True, True, True, "ready", "metric", 13,
       "distance_km * 1000 / visible (tracked) minutes; falls back to minutes_played when visible_minutes is "
       "unknown. Pipeline v1.2 key distance_per_min_m (same definition). Cross-video: sum(distance) / sum(minutes). "
       "Null when those minutes are under 0.1 (too short to be meaningful)."),
    _d("minutes_played", "Minutes played (first to last seen)", "min", "coverage", "float", "sum", None, None, 1.0,
       2, None, False, True, "ready", "metric", 14, "Pipeline v1.2 minutes_played (first to last visible frame). "
       "Older pipelines: video length (duration_s / 60) as an estimate."),
    _d("visible_minutes", "Minutes tracked", "min", "coverage", "float", "sum", None, None, 1.0, 2, None, False,
       True, "ready", "metric", 15, "Pipeline v1.2 visible_minutes: time the player was actually tracked."),
    _d("coverage_pct", "Tracking coverage", "%", "coverage", "float", "avg", None, None, 1.0, 0, None, False, True,
       "ready", "metric", 16, "Pipeline v1.2 coverage_pct: share of video frames with the player tracked "
       "(fragments of one player are added, capped at 100). Cross-video: mean."),
    _d("avg_pitch_x", "Average position (x, along length)", "m", "positional", "float", "avg", None, None, 1.0, 1,
       None, True, True, "ready", "metric", 17, "Pipeline v1.2 avg_pitch_x, else mean pitch_x of the detections."),
    _d("avg_pitch_y", "Average position (y, across width)", "m", "positional", "float", "avg", None, None, 1.0, 1,
       None, True, True, "ready", "metric", 18, "Pipeline v1.2 avg_pitch_y, else mean pitch_y of the detections."),
    # ---- intensity ----
    _d("hsr_distance_km", "High-speed running distance", "km", "intensity", "float", "sum", None, None, 1.0, 2,
       True, True, True, "ready", "metric", 20, "Pipeline key high_speed_distance_km (threshold: meta hsr_threshold_kmh)."),
    _d("sprint_distance_km", "Sprint distance", "km", "intensity", "float", "sum", None, None, 1.0, 2, True, True,
       True, "ready", "metric", 21, "Pipeline key sprint_distance_km (threshold: meta sprint_threshold_kmh)."),
    _d("hsr_count", "High-speed runs", "count", "intensity", "int", "sum", None, None, 1.0, 0, True, True, True,
       "ready", "metric", 22, "Pipeline v1.2 hsr_count: HSR bursts >= 1 s (with hysteresis)."),
    _d("sprint_count", "Sprints", "count", "intensity", "int", "sum", None, None, 1.0, 0, True, True, True, "ready",
       "metric", 23, "Pipeline sprint_count: sprint bursts >= 1 s (v1.1.2+)."),
    _d("high_intensity_efforts", "High-intensity efforts", "count", "intensity", "int", "sum", None, None, 1.0, 0,
       True, True, True, "ready", "metric", 24, "Pipeline v1.2 hi_efforts_count (= hsr_count + sprint_count)."),
    # ---- workload (estimates) ----
    _d("accels", "High accelerations (estimate)", "count", "workload", "int", "sum", None, None, 1.0, 0, True, True,
       True, "ready", "metric", 30, "Pipeline v1.2 accel_count_high (>= 3 m/s2 for >= 0.7 s). Low confidence on "
       "single-camera video."),
    _d("decels", "High decelerations (estimate)", "count", "workload", "int", "sum", None, None, 1.0, 0, True, True,
       True, "ready", "metric", 31, "Pipeline v1.2 decel_count_high (<= -3 m/s2 for >= 0.7 s). Low confidence on "
       "single-camera video."),
    # ---- speed zones (edges: meta zone_edges_kmh; v1.2.0 default 7 / 15 / 20 / 25 km/h) ----
    _d("zone1_distance_km", "Distance: walk zone", "km", "speed_zone", "float", "sum", None, None, 1.0, 2, None,
       True, True, "ready", "metric", 40, "Pipeline zone_walk_km (0 - walk edge)."),
    _d("zone2_distance_km", "Distance: jog zone", "km", "speed_zone", "float", "sum", None, None, 1.0, 2, None,
       True, True, "ready", "metric", 41, "Pipeline zone_jog_km (walk - jog edge)."),
    _d("zone3_distance_km", "Distance: run zone", "km", "speed_zone", "float", "sum", None, None, 1.0, 2, True,
       True, True, "ready", "metric", 42, "Pipeline zone_run_km (jog - run edge)."),
    _d("zone4_distance_km", "Distance: high-speed zone", "km", "speed_zone", "float", "sum", None, None, 1.0, 2,
       True, True, True, "ready", "metric", 43, "Pipeline zone_hsr_km (run - hsr edge)."),
    _d("zone5_distance_km", "Distance: sprint zone", "km", "speed_zone", "float", "sum", None, None, 1.0, 2, True,
       True, True, "ready", "metric", 44, "Pipeline zone_sprint_km (above the hsr edge)."),
]
DEF_BY_KEY = {d["metric_key"]: d for d in DEFINITIONS}
STORED_KEYS = [d["metric_key"] for d in DEFINITIONS if d["storage"] == "metric"]
COLUMN_KEYS = ("distance_km", "top_speed_mph")

# pipeline output key -> our metric key (anything already equal to a stored key maps to itself)
PIPELINE_ALIASES = {
    "high_speed_distance_km": "hsr_distance_km", "hsr_distance_km": "hsr_distance_km",
    "sprint_distance_km": "sprint_distance_km", "sprint_count": "sprint_count", "hsr_count": "hsr_count",
    "high_intensity_efforts": "high_intensity_efforts", "hi_efforts_count": "high_intensity_efforts",
    "accels": "accels", "accel_count": "accels", "accel_count_high": "accels",
    "decels": "decels", "decel_count": "decels", "decel_count_high": "decels",
    "zone_walk_km": "zone1_distance_km", "zone_jog_km": "zone2_distance_km", "zone_run_km": "zone3_distance_km",
    "zone_hsr_km": "zone4_distance_km", "zone_sprint_km": "zone5_distance_km",
    **{f"zone{i}_distance_km": f"zone{i}_distance_km" for i in range(1, 6)},
}
# pipeline keys the adapter reads itself (per track, then combined per player in pipeline._store_metrics)
TRACK_KEYS = {"minutes_played", "visible_minutes", "coverage_pct", "distance_per_min_m", "avg_pitch_x",
              "avg_pitch_y", "top_speed_kmh"}
# known non-metric keys in player_match_stats.json (not warned about). Unknown non-numeric keys (e.g. a future
# player_uid string) are ignored silently; unknown numeric keys are listed in pipeline_meta.warnings.
# CV PR #2 (v2.0, not merged yet) adds per-player keys the adapter reads (seconds / metres precision) or ignores for now
# (player_uid keying comes later): distance_m, minutes_played_s, visible_minutes_s, detected_frames, total_frames,
# player_uid, contributing_track_ids.
PR2_KEYS = {"distance_m", "minutes_played_s", "visible_minutes_s", "detected_frames", "total_frames", "player_uid",
            "contributing_track_ids"}
KNOWN_STAT_KEYS = {"track_id", "jersey_number", "team", "role", "top_speed_mph", "distance_km", "injury_risk",
                   "player_id", "name", *TRACK_KEYS, *PR2_KEYS}
ZONE_NAMES = ("walk", "jog", "run", "hsr", "sprint")   # speed_zones keys <-> zone1..zone5_distance_km

def ensure_definitions(db: Session) -> int:
    """Insert/refresh DEFINITIONS in metric_definitions. Returns rows written; 0 if the table doesn't exist yet."""
    from models import MetricDefinition
    if not inspect(db.get_bind()).has_table("metric_definitions"):
        log.warning("metric_definitions table missing: run migrations/004_player_metrics.sql")
        return 0
    existing = {m.metric_key: m for m in db.scalars(select(MetricDefinition)).all()}
    n = 0
    for d in DEFINITIONS:
        row = existing.get(d["metric_key"])
        if row is None:
            db.add(MetricDefinition(**d, is_active=True))
            n += 1
        else:
            changed = False
            for k, v in d.items():
                if getattr(row, k) != v:
                    setattr(row, k, v)
                    changed = True
            n += changed
    db.commit()
    return n


# --------------------------------------------------------------------------- merging / aggregation
def merge(key: str, a: Optional[float], b: Optional[float]) -> Optional[float]:
    """Combine two values of the same metric (fragmented tracks of one player, or several videos)."""
    if a is None:
        return b
    if b is None:
        return a
    agg = DEF_BY_KEY[key]["aggregation"] if key in DEF_BY_KEY else "sum"
    return max(a, b) if agg == "max" else min(a, b) if agg == "min" else a + b


def aggregate(rows: Iterable[dict], keys: Optional[list[str]] = None) -> dict[str, Optional[float]]:
    """rows = one dict per player_match_stats row: {metric_key: value|None} (columns included).
    Returns {key: aggregated value|None} following each definition's rule, rounded to its decimals."""
    rows = list(rows)
    out: dict[str, Optional[float]] = {}
    for key in keys or [d["metric_key"] for d in DEFINITIONS]:
        d = DEF_BY_KEY.get(key)
        if d is None:
            continue
        agg = d["aggregation"]
        if agg == "ratio":
            num = den = 0.0
            hit = False
            dens = d["ratio_denominator"].split("|")
            for r in rows:
                n = r.get(d["ratio_numerator"])
                m = next((r[k] for k in dens if r.get(k) is not None and r[k] > 0), None)
                if n is not None and m is not None and m > 0:
                    num += n
                    den += m
                    hit = True
            val = (num * d["ratio_scale"] / den) if hit and den >= MIN_RATE_MINUTES else None
            if len(rows) == 1 and rows[0].get(key) is not None:
                # one row: the stored value (pipeline computes it before rounding its inputs), unless the row's own
                # minutes are known and below the floor (rows stored before v0.4.1 could hold e.g. 438,000 m/min)
                r0 = rows[0]
                known = [r0[k] for k in dens if r0.get(k) is not None]
                m0 = next((v for v in known if v > 0), None)
                val = None if known and (m0 is None or m0 < MIN_RATE_MINUTES) else r0[key]
        else:
            vals = [r[key] for r in rows if r.get(key) is not None]
            if not vals:
                val = None
            elif agg == "sum":
                val = sum(vals)
            elif agg == "max":
                val = max(vals)
            elif agg == "min":
                val = min(vals)
            else:  # avg
                val = sum(vals) / len(vals)
        if val is not None:
            val = round(val, d["decimals"])
            if d["value_type"] == "int":
                val = int(round(val))
        out[key] = val
    return out


def avg_position(metrics: dict) -> Optional[dict]:
    x, y = metrics.get("avg_pitch_x"), metrics.get("avg_pitch_y")
    return None if x is None or y is None else {"x": x, "y": y}


def load_rows(db: Session, stats: list) -> dict[int, dict]:
    """{stat_id: {key: value}} for PlayerMatchStat objects/rows (needs .stat_id/.distance_km/.top_speed_mph)."""
    from models import PlayerMatchMetric
    out: dict[int, dict] = {}
    for s in stats:
        out[s.stat_id] = {"distance_km": None if s.distance_km is None else float(s.distance_km),
                          "top_speed_mph": None if s.top_speed_mph is None else float(s.top_speed_mph)}
    ids = list(out)
    for i in range(0, len(ids), 900):
        for m in db.scalars(select(PlayerMatchMetric).where(PlayerMatchMetric.stat_id.in_(ids[i:i + 900]))).all():
            out[m.stat_id][m.metric_key] = m.value
    return out


def parse_keys(raw: Optional[str]) -> Optional[list[str]]:
    """'a,b' -> ['a','b'] (unknown keys dropped); None/'' -> None (= all)."""
    if not raw:
        return None
    return [k for k in (p.strip() for p in raw.split(",")) if k in DEF_BY_KEY] or None


# --------------------------------------------------------------------------- heatmap
def pitch_dims(calibration_path) -> tuple[float, float]:
    """(length_m, width_m) from a calibration JSON's pitch_dimensions, else 105 x 68."""
    try:
        data = json.loads(open(calibration_path).read()) if calibration_path else None
        pd = (data or {}).get("pitch_dimensions") or {}
        length, width = float(pd.get("length_m")), float(pd.get("width_m"))
        if length > 0 and width > 0:
            return length, width
    except Exception:  # noqa: BLE001 - missing/invalid file -> default
        pass
    return DEFAULT_PITCH


def heatmap(points: list[tuple[float, float]], length: float, width: float, margin: float = 5.0):
    """-> (cells[rows][cols] counts, samples, (mean_x, mean_y) | None). Points > margin off the pitch are dropped,
    the rest are clamped onto the pitch."""
    cells = [[0] * GRID_COLS for _ in range(GRID_ROWS)]
    xs, ys = [], []
    for x, y in points:
        if not (-margin <= x <= length + margin and -margin <= y <= width + margin):
            continue
        x, y = min(max(x, 0.0), length), min(max(y, 0.0), width)
        c = min(int(x / length * GRID_COLS), GRID_COLS - 1)
        r = min(int(y / width * GRID_ROWS), GRID_ROWS - 1)
        cells[r][c] += 1
        xs.append(x)
        ys.append(y)
    mean = (sum(xs) / len(xs), sum(ys) / len(ys)) if xs else None
    return cells, len(xs), mean


def sum_grids(grids: Iterable[list[list[float]]], cols: int = GRID_COLS, rows: int = GRID_ROWS) -> list[list]:
    """Cell-wise sum of same-sized grids (ints stay ints)."""
    total = [[0] * cols for _ in range(rows)]
    for g in grids:
        for r, row in enumerate(g[:rows]):
            for c, v in enumerate(row[:cols]):
                total[r][c] += v
    return [[round(v, 3) if isinstance(v, float) else v for v in row] for row in total]


def normalize(cells: list[list[float]]) -> list[list[float]]:
    peak = max((v for row in cells for v in row), default=0)
    return [[round(v / peak, 3) if peak else 0.0 for v in row] for row in cells]


def valid_grid(g) -> Optional[tuple[int, int]]:
    """(cols, rows) if g is a non-empty rectangular list of numeric rows, else None."""
    if not isinstance(g, list) or not g or not all(isinstance(r, list) and r for r in g):
        return None
    cols = len(g[0])
    if any(len(r) != cols for r in g):
        return None
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 for r in g for v in r):
        return None
    return cols, len(g)


def combine_heatmaps(maps: list) -> dict:
    """Sum PlayerHeatmap rows that share one grid (cols, rows, source, unit). Grids of different shapes/units can't be
    added, so the group with the most samples wins (tie: pipeline grid); the others are counted in `skipped`."""
    groups: dict[tuple, list] = defaultdict(list)
    for h in maps:
        groups[(h.grid_cols, h.grid_rows, h.source or "backend", h.cell_unit or "samples")].append(h)
    if not groups:
        return {"cols": GRID_COLS, "rows": GRID_ROWS, "source": None, "cell_unit": None, "samples": 0,
                "counts": [[0] * GRID_COLS for _ in range(GRID_ROWS)], "pitch_length_m": DEFAULT_PITCH[0],
                "pitch_width_m": DEFAULT_PITCH[1], "used": [], "skipped": 0}
    key = max(groups, key=lambda k: (sum(h.samples for h in groups[k]), k[2] == "pipeline"))
    chosen = groups[key]
    cols, rows = key[0], key[1]
    counts = sum_grids([json.loads(h.cells) for h in chosen], cols, rows)
    return {"cols": cols, "rows": rows, "source": key[2], "cell_unit": key[3],
            "samples": sum(h.samples for h in chosen), "counts": counts,
            "pitch_length_m": chosen[0].pitch_length_m, "pitch_width_m": chosen[0].pitch_width_m,
            "used": [h.stat_id for h in chosen], "skipped": len(maps) - len(chosen)}


# --------------------------------------------------------------------------- SQL seed (migrations / schema.sql)
def _sql(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def definitions_insert_sql() -> str:
    """The INSERT ... ON DUPLICATE KEY UPDATE used in migrations/004, 006 and schema.sql (kept in sync by a test)."""
    cols = list(_F) + ["is_active"]
    rows = ",\n".join("  (" + ", ".join(_sql(d[c]) for c in _F) + ", 1)"
                      for d in sorted(DEFINITIONS, key=lambda d: d["sort_order"]))
    upd = ",\n  ".join(f"{c} = VALUES({c})" for c in cols if c != "metric_key")
    return (f"INSERT INTO metric_definitions\n  ({', '.join(cols)})\nVALUES\n{rows}\n"
            f"ON DUPLICATE KEY UPDATE\n  {upd};\n")
