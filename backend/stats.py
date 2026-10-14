"""Shared per-player aggregation used by /api/players/stats and /api/videos/{id}/stats."""
from typing import Optional

from sqlalchemy import case, func, inspect, select
from sqlalchemy.orm import Session

import metrics_catalog as mc
from models import Player, PlayerHeatmap, PlayerMatchStat, VideoPlayerOverride
from schemas import PlayerStatMetricsOut, PlayerStatOut

RISK_RANK = {"Low": 1, "Medium": 2, "High": 3}
FATIGUE_SCORE = {"Low": 0.0, "Medium": 50.0, "High": 100.0}
MPH_TO_KMH = 1.609344

def fatigue_score(risk: Optional[str]) -> Optional[float]:
    return FATIGUE_SCORE.get(risk) if risk else None

def meters_from_km(km) -> Optional[float]:
    return None if km is None else round(float(km) * 1000.0, 2)

def kmh_from_mph(mph) -> Optional[float]:
    return None if mph is None else round(float(mph) * MPH_TO_KMH, 2)

_overrides_table = False


def has_overrides_table(db: Session) -> bool:
    """True once migration 007 (video_player_overrides) exists. Checked until found, then cached, so the API keeps
    working if the new code is deployed before the migration is run (overrides are then simply absent)."""
    global _overrides_table
    if not _overrides_table:
        _overrides_table = inspect(db.get_bind()).has_table(VideoPlayerOverride.__tablename__)
    return _overrides_table
RANK_RISK = {v: k for k, v in RISK_RANK.items()}


def aggregate_player_stats(
    db: Session, match_id: Optional[int] = None, team_id: Optional[int] = None, video_id: Optional[int] = None,
    include_metrics: bool = False, metric_keys: Optional[list[str]] = None, flat: bool = False,
) -> list[PlayerStatOut]:
    """Max top speed, total distance, worst injury risk per player. Players with no stats rows are excluded.
    MAX/SUM ignore NULLs; if all of a player's values are NULL (no calibration) the field is null."""
    risk_rank = case(RISK_RANK, value=PlayerMatchStat.injury_risk, else_=1)
    stmt = (
        select(
            Player.player_id,
            Player.first_name,
            Player.last_name,
            Player.jersey_number,
            func.max(PlayerMatchStat.top_speed_mph).label("top_speed"),
            func.sum(PlayerMatchStat.distance_km).label("distance"),
            func.max(risk_rank).label("risk_rank"),
        )
        .join(PlayerMatchStat, PlayerMatchStat.player_id == Player.player_id)
        .group_by(Player.player_id, Player.first_name, Player.last_name, Player.jersey_number)
        .order_by(Player.player_id)
    )
    if match_id is not None:
        stmt = stmt.where(PlayerMatchStat.match_id == match_id)
    if video_id is not None:
        stmt = stmt.where(PlayerMatchStat.video_id == video_id)
    if team_id is not None:
        stmt = stmt.where(Player.team_id == team_id)

    per_player: dict[int, dict] = {}
    if include_metrics or flat:
        q = select(PlayerMatchStat).join(Player, Player.player_id == PlayerMatchStat.player_id)
        if match_id is not None:
            q = q.where(PlayerMatchStat.match_id == match_id)
        if video_id is not None:
            q = q.where(PlayerMatchStat.video_id == video_id)
        if team_id is not None:
            q = q.where(Player.team_id == team_id)
        stats = db.scalars(q).all()
        values = mc.load_rows(db, stats)
        grouped: dict[int, list[dict]] = {}
        stat_ids: dict[int, list[int]] = {}
        for st in stats:
            grouped.setdefault(st.player_id, []).append(values[st.stat_id])
            stat_ids.setdefault(st.player_id, []).append(st.stat_id)
        maps: dict[int, PlayerHeatmap] = {}
        if flat and stats:
            maps = {h.stat_id: h for h in db.scalars(select(PlayerHeatmap).where(
                PlayerHeatmap.stat_id.in_([st.stat_id for st in stats])))}
        keys = metric_keys or [d["metric_key"] for d in mc.DEFINITIONS]
        all_keys = [d["metric_key"] for d in mc.DEFINITIONS]
        for pid, rows in grouped.items():
            agg = mc.aggregate(rows, all_keys)
            extra: dict = {"avg_position": mc.avg_position(agg)}
            if include_metrics:
                extra["metrics"] = {k: agg.get(k) for k in keys}
            if flat:
                extra.update({k: agg.get(k) for k in FLAT_KEYS})
                zones = {name: agg.get(f"zone{i}_distance_km") for i, name in enumerate(ZONE_NAMES, 1)}
                extra["speed_zones"] = zones if any(v is not None for v in zones.values()) else None
                extra["heatmap"] = _flat_heatmap([maps[i] for i in stat_ids[pid] if i in maps])
            per_player[pid] = extra

    # per-video jersey corrections (PATCH /api/videos/{id}/players/{player_id}) apply to that video's rows only
    overrides = {} if video_id is None or not flat or not has_overrides_table(db) else {
        o.player_id: o.jersey_number
        for o in db.scalars(select(VideoPlayerOverride).where(VideoPlayerOverride.video_id == video_id))}
    cls = PlayerStatMetricsOut if (include_metrics or flat) else PlayerStatOut
    out = []
    for row in db.execute(stmt).all():
        kw = {}
        if include_metrics or flat:
            kw = per_player.get(row.player_id) or {"avg_position": None}
            if include_metrics:
                kw.setdefault("metrics", {})
            if flat:
                kw = {**{k: None for k in FLAT_KEYS}, "speed_zones": None, "heatmap": None, **kw,
                      "jersey_number": overrides.get(row.player_id, row.jersey_number)}
        risk = RANK_RISK.get(int(row.risk_rank or 1), "Low")
        mph = None if row.top_speed is None else round(float(row.top_speed), 2)
        km = None if row.distance is None else round(float(row.distance), 3)
        if flat or include_metrics:
            # ERD names: prefer metric-aggregate values already in kw; else derive from mph/km/risk
            kw.setdefault("top_speed_kmh", kmh_from_mph(mph))
            if kw.get("top_speed_kmh") is None:
                kw["top_speed_kmh"] = kmh_from_mph(mph)
            kw.setdefault("distance_covered_meters", meters_from_km(km))
            if kw.get("distance_covered_meters") is None:
                kw["distance_covered_meters"] = meters_from_km(km)
            kw.setdefault("fatigue_risk_score", fatigue_score(risk))
            if kw.get("fatigue_risk_score") is None:
                kw["fatigue_risk_score"] = fatigue_score(risk)
        out.append(cls(
            player_id=row.player_id,
            name=f"{row.first_name} {row.last_name}",
            # Decimal -> float so JSON gets numbers, not strings
            top_speed_mph=mph,
            distance_km=km,
            injury_risk=risk,
            **kw,
        ))
    return out


FLAT_KEYS = ("top_speed_kmh", "distance_covered_meters", "fatigue_risk_score", "minutes_played",
             "visible_minutes", "coverage_pct", "distance_per_min",
             "hsr_distance_km", "sprint_distance_km", "hsr_count", "sprint_count", "high_intensity_efforts",
             "accels", "decels")
ZONE_NAMES = mc.ZONE_NAMES


def _flat_heatmap(maps: list) -> Optional[dict]:
    if not maps:
        return None
    g = mc.combine_heatmaps(maps)
    norm = mc.normalize(g["counts"])
    return {"cols": g["cols"], "rows": g["rows"], "cells": [v for r in norm for v in r], "samples": g["samples"],
            "source": g["source"], "cell_unit": g["cell_unit"], "pitch_length_m": g["pitch_length_m"],
            "pitch_width_m": g["pitch_width_m"]}


def wants_metrics(include: Optional[str]) -> bool:
    """?include=metrics (comma-separated list accepted)."""
    return bool(include) and "metrics" in {p.strip().lower() for p in include.split(",")}
