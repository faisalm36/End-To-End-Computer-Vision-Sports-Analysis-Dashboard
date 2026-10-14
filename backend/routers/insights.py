"""Tag insights: how do your matches with each value of a tag key compare, and what happens in the NEXT match?

Unit of analysis = a match. Per match we first combine each player's rows across your videos of that match
(metric aggregation rules), then average over the players in scope:
  - default scope: players of YOUR team in that match (match_logic.effective_side)
  - ?team_id=: players of that team (must be yours)      - ?player_id=: just that player (must be yours)
Group averages are the mean of the per-match averages (each match weighs the same); n is reported everywhere,
nulls are skipped (a metric nobody has is null, never 0).

avg_workload = mean of the pipeline's workload-based injury-risk band per player appearance
(Low = 1, Medium = 2, High = 3; range 1-3; built from distance, sprint count and HSR distance).
It's a workload indicator, not medical advice.
"""
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

import metrics_catalog as mc
import tagging
from database import get_db
from match_logic import match_result, our_team_id, user_match_ids_stmt
from models import Match, MatchTag, MatchVideo, Player, PlayerMatchStat, TagKey, TagValue, Team, User
from security import get_current_user
from stats import RISK_RANK, fatigue_score, kmh_from_mph, meters_from_km

router = APIRouter(prefix="/api/insights", tags=["insights"])

METRICS = ["distance_km", "top_speed_mph", "sprint_count", "hsr_distance_km", "sprint_distance_km",
           "distance_per_min"]
ALL = METRICS + ["workload"]
EFFECT_METRICS = ["distance_km", "top_speed_mph", "sprint_count", "hsr_distance_km", "workload"]
# next_match_effect.metric uses the frontend's short names; metric_key is the registry key
EFFECT_NAMES = {"distance_km": "distance", "top_speed_mph": "speed", "sprint_count": "sprints",
                "hsr_distance_km": "hsr", "workload": "workload"}
LOW_SAMPLE = 3
WORKLOAD_DOC = ("avg_workload = mean workload band per player appearance from the pipeline's workload-based "
                "injury-risk (Low=1, Medium=2, High=3; range 1-3). Workload indicator, not medical advice.")


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)


def _round(k, v):
    if v is None:
        return None
    return round(v, 1 if k in ("top_speed_mph", "distance_per_min", "sprint_count") else 3 if k == "workload" else 3)


def _per_match(db: Session, user: User, matches: dict[int, Match], player_id, team_id) -> dict[int, dict]:
    """{match_id: {"metrics": {k: avg}, "n_players": n, "risk": {Low,Medium,High}}} for matches with data."""
    q = (select(PlayerMatchStat, Player.team_id)
         .join(Player, Player.player_id == PlayerMatchStat.player_id)
         .outerjoin(MatchVideo, MatchVideo.video_id == PlayerMatchStat.video_id)
         .where(PlayerMatchStat.match_id.in_(list(matches) or [-1]),
                or_(PlayerMatchStat.video_id.is_(None),
                    (MatchVideo.user_id == user.user_id) & (MatchVideo.processing_status == "done"))))
    if player_id is not None:
        q = q.where(PlayerMatchStat.player_id == player_id)
    elif team_id is not None:
        q = q.where(Player.team_id == team_id)
    rows = [(st, tid) for st, tid in db.execute(q).all()
            if player_id is not None or team_id is not None
            or tid == our_team_id(matches[st.match_id], user.user_id)]
    values = mc.load_rows(db, [st for st, _ in rows])
    by_mp: dict[tuple[int, int], list] = defaultdict(list)
    for st, _ in rows:
        by_mp[(st.match_id, st.player_id)].append(st)
    per_match: dict[int, dict] = {}
    for (mid, _pid), sts in by_mp.items():
        agg = mc.aggregate([values[s.stat_id] for s in sts], METRICS)
        agg["workload"] = float(max(RISK_RANK.get(s.injury_risk, 1) for s in sts))
        pm = per_match.setdefault(mid, {"players": [], "risk": {"Low": 0, "Medium": 0, "High": 0}})
        pm["players"].append(agg)
        pm["risk"][{1: "Low", 2: "Medium", 3: "High"}[int(agg["workload"])]] += 1
    out = {}
    for mid, pm in per_match.items():
        out[mid] = {"metrics": {k: _mean([p.get(k) for p in pm["players"]])[0] for k in ALL},
                    "n_players": len(pm["players"]), "risk": pm["risk"]}
    return out


def _summary(match_ids: list[int], per_match: dict, results: dict[int, Optional[str]]) -> dict:
    with_data = [m for m in match_ids if m in per_match]
    metrics, metric_n = {}, {}
    for k in ALL:
        v, n = _mean([per_match[m]["metrics"][k] for m in with_data])
        metrics[k], metric_n[k] = _round(k, v), n
    risk = {"Low": 0, "Medium": 0, "High": 0}
    for m in with_data:
        for b, c in per_match[m]["risk"].items():
            risk[b] += c
    wdl = {"w": 0, "d": 0, "l": 0, "unknown": 0}
    for m in match_ids:
        wdl[{"W": "w", "D": "d", "L": "l"}.get(results.get(m), "unknown")] += 1
    return {"matches": len(match_ids), "matches_with_data": len(with_data), "low_sample": len(with_data) < LOW_SAMPLE,
            "metrics": metrics, "metric_n": metric_n, "injury_risk": risk, "wdl": wdl, "match_ids": match_ids}


def _vs(metrics: dict, baseline: dict) -> tuple[dict, dict]:
    delta, pct = {}, {}
    for k in ALL:
        a, b = metrics.get(k), baseline.get(k)
        delta[k] = None if a is None or b is None else _round(k, a - b)
        pct[k] = None if a is None or b in (None, 0) else round((a - b) / b * 100.0, 1)
    return delta, pct


def compute(db: Session, user: User, key: str, player_id: Optional[int], team_id: Optional[int]) -> dict:
    key = tagging.norm_key(key)
    if player_id is not None:
        p = db.get(Player, player_id)
        if p is None or p.team is None or p.team.user_id != user.user_id:
            raise HTTPException(status_code=404, detail="Player not found")
    if team_id is not None:
        t = db.get(Team, team_id)
        if t is None or t.user_id != user.user_id:
            raise HTTPException(status_code=404, detail="Team not found")
    ms = db.scalars(select(Match).options(joinedload(Match.home_team), joinedload(Match.away_team))
                    .where(Match.match_id.in_(user_match_ids_stmt(user.user_id)))
                    .order_by(Match.match_date, Match.match_id)).all()
    if team_id is not None:
        ms = [m for m in ms if team_id in (m.home_team_id, m.away_team_id)]
    matches = {m.match_id: m for m in ms}
    order = [m.match_id for m in ms]
    nxt = {a: b for a, b in zip(order, order[1:])}
    results = {m.match_id: match_result(m, user.user_id) for m in ms}
    per_match = _per_match(db, user, matches, player_id, team_id)

    base = _summary(order, per_match, results)
    baseline = base["metrics"]

    tagged: dict[str, list[int]] = defaultdict(list)
    for mid, val in db.execute(
            select(MatchTag.match_id, TagValue.value)
            .join(TagValue, TagValue.tag_value_id == MatchTag.tag_value_id)
            .join(TagKey, TagKey.tag_key_id == TagValue.tag_key_id)
            .where(TagKey.user_id == user.user_id, func.lower(TagKey.name) == key.lower(),
                   MatchTag.match_id.in_(list(matches) or [-1]))).all():
        tagged[val].append(mid)

    groups, effects = [], []
    for val in sorted(tagged, key=lambda v: (-len(tagged[v]), v.lower())):
        mids = sorted(set(tagged[val]), key=order.index)
        g = _summary(mids, per_match, results)
        g_delta, g_pct = _vs(g["metrics"], baseline)
        next_ids = list(dict.fromkeys(nxt[m] for m in mids if m in nxt))
        pairs = sum(1 for m in mids if m in nxt and m in per_match and nxt[m] in per_match)
        n = _summary(next_ids, per_match, results)
        n_delta, n_pct = _vs(n["metrics"], baseline)
        n["delta"], n["change_pct"], n["pairs"] = n_delta, n_pct, pairs
        groups.append({
            "value": val, "matches": g["matches"], "matches_with_data": g["matches_with_data"],
            "low_sample": g["low_sample"],
            "avg_distance_km": g["metrics"]["distance_km"],
            "avg_distance_covered_meters": meters_from_km(g["metrics"]["distance_km"]),
            "avg_top_speed_mph": g["metrics"]["top_speed_mph"],
            "avg_top_speed_kmh": kmh_from_mph(g["metrics"]["top_speed_mph"]),
            "avg_sprints": g["metrics"]["sprint_count"], "avg_sprint_count": g["metrics"]["sprint_count"],
            "avg_hsr_distance_km": g["metrics"]["hsr_distance_km"],
            "avg_sprint_distance_km": g["metrics"]["sprint_distance_km"],
            "avg_distance_per_min": g["metrics"]["distance_per_min"], "avg_workload": g["metrics"]["workload"],
            "metrics": g["metrics"], "metric_n": g["metric_n"], "delta_vs_baseline": g_delta,
            "change_pct_vs_baseline": g_pct, "injury_risk": g["injury_risk"],
            "avg_fatigue_risk_score": (None if g["metrics"]["workload"] is None
                                       else round((g["metrics"]["workload"] - 1) * 50.0, 2)),
            "workload": {b.lower(): c for b, c in g["injury_risk"].items()}, "wdl": g["wdl"],
            "match_ids": mids, "next_match": n,
        })
        for k in EFFECT_METRICS:
            effects.append({"value": val, "metric": EFFECT_NAMES[k], "metric_key": k, "change_pct": n_pct[k],
                            "delta": n_delta[k], "next": n["metrics"][k], "next_avg": n["metrics"][k],
                            "baseline": baseline[k], "n": n["metric_n"][k], "pairs": pairs,
                            "low_sample": n["metric_n"][k] < LOW_SAMPLE})
    base.pop("low_sample")
    return {"key": key, "filters": {"player_id": player_id, "team_id": team_id},
            "scope": "player" if player_id is not None else "team" if team_id is not None else "our_team",
            "definitions": {"avg_workload": WORKLOAD_DOC,
                            "unit_of_analysis": "match; per-match value = mean over players in scope",
                            "next_match": "your next match chronologically after each tagged match (deduplicated)",
                            "low_sample": f"true when fewer than {LOW_SAMPLE} matches have data"},
            "baseline": {**base, "avg_distance_km": baseline["distance_km"],
                         "avg_distance_covered_meters": meters_from_km(baseline["distance_km"]),
                         "avg_top_speed_mph": baseline["top_speed_mph"],
                         "avg_top_speed_kmh": kmh_from_mph(baseline["top_speed_mph"]),
                         "avg_sprints": baseline["sprint_count"], "avg_sprint_count": baseline["sprint_count"],
                         "avg_hsr_distance_km": baseline["hsr_distance_km"], "avg_workload": baseline["workload"],
                         "avg_fatigue_risk_score": (None if baseline["workload"] is None
                                                    else round((baseline["workload"] - 1) * 50.0, 2)),
                         "workload": {b.lower(): c for b, c in base["injury_risk"].items()}},
            "groups": groups, "next_match_effect": effects}


@router.get("/tags")
def insights_tags(key: str = Query(..., description="Tag key, e.g. weather"),
                  player_id: Optional[int] = Query(None), team_id: Optional[int] = Query(None),
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return compute(db, user, key, player_id, team_id)


@router.get("")
def insights(tag_key: Optional[str] = Query(None, description="Tag key (alias: key)"),
             key: Optional[str] = Query(None), player_id: Optional[int] = Query(None),
             team_id: Optional[int] = Query(None),
             db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Same response as /api/insights/tags (frontend contract name)."""
    k = tag_key or key
    if not k:
        raise RequestValidationError([{"type": "missing", "loc": ("query", "tag_key"), "msg": "Field required",
                                       "input": None}])
    return compute(db, user, k, player_id, team_id)
