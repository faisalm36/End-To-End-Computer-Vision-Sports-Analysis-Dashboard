"""Metric registry, per-player metric history, heatmaps."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

import metrics_catalog as mc
from database import get_db
from match_logic import match_result
from models import Match, MatchVideo, MetricDefinition, Player, PlayerHeatmap, PlayerMatchStat, User
from routers.videos import _get_user_video, not_ready_response
from security import get_current_user
from stats import RANK_RISK, RISK_RANK, fatigue_score, kmh_from_mph, meters_from_km

router = APIRouter(tags=["metrics"])

AXES = {"x_axis": "pitch length (pitch_x, m)", "y_axis": "pitch width (pitch_y, m)",
        "layout": "counts[row][col], row 0 = pitch_y 0, col 0 = pitch_x 0"}


def _grid_info(g: dict) -> dict:
    """source: pipeline = CV heatmaps.json (v1.2.0+, 21x14, cell_unit seconds);
    backend = computed from tracking_detections (fallback, 12x8, cell_unit samples)."""
    return {"cols": g["cols"], "rows": g["rows"], **AXES, "source": g["source"], "cell_unit": g["cell_unit"],
            "pitch_length_m": g["pitch_length_m"], "pitch_width_m": g["pitch_width_m"]}


def _def_out(d: MetricDefinition | dict) -> dict:
    g = (lambda k: d[k]) if isinstance(d, dict) else (lambda k: getattr(d, k))
    return {"key": g("metric_key"), "label": g("label"), "unit": g("unit"), "category": g("category"),
            "value_type": g("value_type"), "aggregation": g("aggregation"), "decimals": g("decimals"),
            "higher_is_better": g("higher_is_better"), "requires_calibration": bool(g("requires_calibration")),
            "is_estimate": bool(g("is_estimate")), "availability": g("availability"), "storage": g("storage"),
            "description": g("description"), "sort_order": g("sort_order")}


@router.get("/api/metrics")
def list_metrics(db: Session = Depends(get_db)) -> list[dict]:
    """Public registry of per-player metrics (label, unit, aggregation rule, availability ready|soon, ...)."""
    rows = db.scalars(select(MetricDefinition).where(MetricDefinition.is_active.is_(True))
                      .order_by(MetricDefinition.sort_order, MetricDefinition.metric_key)).all()
    return [_def_out(r) for r in rows] if rows else [_def_out(d) for d in mc.DEFINITIONS]


def _user_player(db: Session, user: User, player_id: int) -> Player:
    p = db.get(Player, player_id)
    if p is None or p.team is None or p.team.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Player not found")
    return p


def _player_stats(db: Session, user: User, player_id: int, video_id: Optional[int] = None,
                  match_id: Optional[int] = None) -> list[tuple[PlayerMatchStat, Optional[MatchVideo], Match]]:
    """The player's stats rows from your done videos (+ legacy rows without a video), oldest match first."""
    q = (select(PlayerMatchStat, MatchVideo, Match)
         .join(Match, Match.match_id == PlayerMatchStat.match_id)
         .outerjoin(MatchVideo, MatchVideo.video_id == PlayerMatchStat.video_id)
         .where(PlayerMatchStat.player_id == player_id,
                or_(PlayerMatchStat.video_id.is_(None),
                    (MatchVideo.user_id == user.user_id) & (MatchVideo.processing_status == "done"))))
    if video_id is not None:
        q = q.where(PlayerMatchStat.video_id == video_id)
    if match_id is not None:
        q = q.where(PlayerMatchStat.match_id == match_id)
    return list(db.execute(q.order_by(Match.match_date, Match.match_id, PlayerMatchStat.video_id)).all())


@router.get("/api/players/{player_id}/metrics")
def player_metrics(player_id: int,
                   metrics: Optional[str] = Query(None, description="Comma-separated metric keys (default: all)"),
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Per-video history (one entry per stats row, oldest first) + totals. Your players only (404 otherwise)."""
    p = _user_player(db, user, player_id)
    keys = mc.parse_keys(metrics) or [d["metric_key"] for d in mc.DEFINITIONS]
    keys_pos = list(dict.fromkeys(keys + ["avg_pitch_x", "avg_pitch_y"]))
    rows = _player_stats(db, user, player_id)
    values = mc.load_rows(db, [r[0] for r in rows])
    series = []
    for st, v, m in rows:
        agg = mc.aggregate([values[st.stat_id]], keys_pos)
        mph, km = agg.get("top_speed_mph"), agg.get("distance_km")
        # Prefer column values when present (ingest wrote them); else derive / use metrics.
        kmh = float(st.top_speed_kmh) if st.top_speed_kmh is not None else (
            agg.get("top_speed_kmh") if agg.get("top_speed_kmh") is not None else kmh_from_mph(mph))
        meters = float(st.distance_covered_meters) if st.distance_covered_meters is not None else meters_from_km(km)
        mins = st.minutes_played if st.minutes_played is not None else agg.get("minutes_played")
        spr = st.sprint_count if st.sprint_count is not None else agg.get("sprint_count")
        fat = float(st.fatigue_risk_score) if st.fatigue_risk_score is not None else fatigue_score(st.injury_risk)
        series.append({
            "video_id": st.video_id, "video_title": v.title if v else None, "match_id": m.match_id,
            "match_date": m.match_date.isoformat(), "home_team": m.home_team.team_name,
            "away_team": m.away_team.team_name, "result": match_result(m, user.user_id),
            "top_speed_mph": mph, "top_speed_kmh": kmh,
            "distance_km": km, "distance_covered_meters": meters,
            "injury_risk": st.injury_risk, "fatigue_risk_score": fat,
            "minutes_played": mins, "sprint_count": None if spr is None else int(spr),
            "metrics": {k: agg.get(k) for k in keys},
            "avg_position": mc.avg_position(agg),
        })
    tot = mc.aggregate([values[r[0].stat_id] for r in rows], keys_pos)
    worst = max((RISK_RANK.get(r[0].injury_risk, 1) for r in rows), default=None)
    risk = RANK_RISK[worst] if worst else None
    t_mph, t_km = tot.get("top_speed_mph"), tot.get("distance_km")
    return {"player_id": p.player_id, "name": f"{p.first_name} {p.last_name}".strip(), "team_id": p.team_id,
            "series": series,
            "totals": {"appearances": len(rows), "top_speed_mph": t_mph, "top_speed_kmh": kmh_from_mph(t_mph),
                       "distance_km": t_km, "distance_covered_meters": meters_from_km(t_km),
                       "injury_risk": risk, "fatigue_risk_score": fatigue_score(risk),
                       "minutes_played": tot.get("minutes_played"),
                       "sprint_count": None if tot.get("sprint_count") is None else int(tot.get("sprint_count")),
                       "metrics": {k: tot.get(k) for k in keys}, "avg_position": mc.avg_position(tot)}}


@router.get("/api/videos/{video_id}/heatmap")
def video_heatmap(video_id: int, player_id: Optional[int] = Query(None),
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Per-player occupancy grids for one video. 409 (same body as /stats) until done."""
    v = _get_user_video(db, user, video_id)
    if (resp := not_ready_response(v)) is not None:
        return resp
    q = (select(PlayerMatchStat, Player).join(Player, Player.player_id == PlayerMatchStat.player_id)
         .where(PlayerMatchStat.video_id == video_id))
    if player_id is not None:
        q = q.where(PlayerMatchStat.player_id == player_id)
    rows = db.execute(q.order_by(Player.player_id)).all()
    maps = {h.stat_id: h for h in db.scalars(select(PlayerHeatmap).where(
        PlayerHeatmap.stat_id.in_([st.stat_id for st, _ in rows] or [-1]))).all()}
    values = mc.load_rows(db, [st for st, _ in rows])
    players, grids = [], []
    for st, p in rows:
        h = maps.get(st.stat_id)
        g = mc.combine_heatmaps([h] if h else [])
        if h:
            grids.append(g)
        agg = mc.aggregate([values[st.stat_id]], ["avg_pitch_x", "avg_pitch_y"])
        players.append({"player_id": p.player_id, "name": f"{p.first_name} {p.last_name}".strip(),
                        "samples": g["samples"], "avg_position": mc.avg_position(agg),
                        "cols": g["cols"], "rows": g["rows"], "source": g["source"], "cell_unit": g["cell_unit"],
                        "counts": g["counts"], "intensity": mc.normalize(g["counts"])})
    # top-level grid = the most common one in this video (players carry their own cols/rows/source too)
    top = max(grids, key=lambda g: sum(1 for o in grids if (o["cols"], o["rows"]) == (g["cols"], g["rows"])),
              default=mc.combine_heatmaps([]))
    return {"video_id": v.video_id, "grid": _grid_info(top), "players": players}


@router.get("/api/players/{player_id}/heatmap")
def player_heatmap(player_id: int, video_id: Optional[int] = Query(None), match_id: Optional[int] = Query(None),
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """The player's grid summed over your videos (optionally one video / match)."""
    p = _user_player(db, user, player_id)
    rows = _player_stats(db, user, player_id, video_id=video_id, match_id=match_id)
    maps = db.scalars(select(PlayerHeatmap).where(
        PlayerHeatmap.stat_id.in_([r[0].stat_id for r in rows] or [-1]))).all()
    g = mc.combine_heatmaps(list(maps))
    used = [h for h in maps if h.stat_id in set(g["used"])]
    # sample-weighted average position across the videos whose grid was used
    values = mc.load_rows(db, [r[0] for r in rows])
    wx = wy = w = 0.0
    for h in used:
        vals = values.get(h.stat_id, {})
        if vals.get("avg_pitch_x") is not None and vals.get("avg_pitch_y") is not None and h.samples:
            wx += vals["avg_pitch_x"] * h.samples
            wy += vals["avg_pitch_y"] * h.samples
            w += h.samples
    return {"player_id": p.player_id, "name": f"{p.first_name} {p.last_name}".strip(),
            "videos": len(used), "videos_skipped": g["skipped"],
            "grid": _grid_info(g), "samples": g["samples"],
            "avg_position": {"x": round(wx / w, 1), "y": round(wy / w, 1)} if w else None,
            "counts": g["counts"], "intensity": mc.normalize(g["counts"])}
