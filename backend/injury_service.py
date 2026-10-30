"""Roster injury-risk service (model rir-1.0, v0.9.0). Runs alongside the ML scorer in risk_service.py.

Builds model inputs from the DB (player_injuries, player_match_stats + matches.surface, players.birth_date), scores
current / previous (one per past match) / projected next match, and persists encrypted snapshots on every write
path (injury CRUD, match surface edit, match ingest via recompute_for_match()).
NOT MEDICAL ADVICE: a screening/education index; selection and return-to-play decisions belong to medical staff.
"""
import logging
from collections import defaultdict
from datetime import date
from typing import Iterable, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import health_crypto as hc
from config import settings
from injury_risk import risk_model as rm
from models import Match, Player, PlayerInjury, PlayerMatchStat, PlayerRiskSnapshot

log = logging.getLogger("injury_risk")

DISCLAIMER = ("Screening/education index only - not medical advice or a diagnosis. Return-to-play and selection "
              "decisions belong to qualified medical staff.")
SURFACES = ("grass", "turf", "hybrid", "indoor", "unknown")

CITATIONS = {
    "previous_injury": "Hagglund et al. 2006, BJSM - doi:10.1136/bjsm.2006.026609",
    "turf_ankle": "Ekstrand et al. 2006, BJSM - doi:10.1136/bjsm.2006.027623",
    "congestion": "Bengtsson et al. 2013, BJSM - doi:10.1136/bjsports-2013-092383",
    "turf_streak": "Design choice (Kuitunen et al. 2023 meta-analysis: no overall turf effect - doi:10.1016/j.eclinm.2023.101956)",
    "surface_switch": "Design choice (Williams et al. 2011 review hypothesis)",
    "acwr_high": "Design choice; ACWR is contested (Impellizzeri et al. 2020)",
    "acwr_low": "Design choice; ACWR is contested (Impellizzeri et al. 2020)",
    "recent_return": "Design choice (re-injury window, Ekstrand et al. 2011)",
    "severe_injury": "Design choice (UEFA severity >28 days)",
    "recurrent_site": "Design choice informed by Hagglund 2006 / Arnason 2004",
    "age": "Design choice (attenuated Arnason 2004 age effect)",
    "currently_injured": "Player is inside an injury window (no return date reached)",
}


def _key() -> Optional[bytes]:
    try:
        return hc.parse_key(settings.HEALTH_DATA_KEY)
    except hc.HealthKeyError:
        return None


def encrypt_notes(notes: Optional[str]) -> Optional[str]:
    if not notes:
        return None
    key = _key()
    if key is None:
        raise hc.HealthKeyError("HEALTH_DATA_KEY is not configured")
    return hc.encrypt_json(notes, key)


def decrypt_notes(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    key = _key()
    try:
        return hc.decrypt_json(token, key) if key else None
    except Exception:  # noqa: BLE001
        return None


def norm_surface(s: Optional[str]) -> Optional[str]:
    s = (s or "").strip().lower()
    if s in ("turf", "indoor"):
        return "turf"
    if s in ("grass", "hybrid"):
        return "grass"
    return None


def age_on(birth: Optional[date], on: date) -> Optional[int]:
    if not birth:
        return None
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


# ------------------------------------------------------------------ inputs
def load_inputs(db: Session, player_ids: Iterable[int]) -> dict:
    pids = sorted(set(player_ids))
    out = {pid: {"injuries": [], "matches": []} for pid in pids}
    if not pids:
        return out
    for inj in db.scalars(select(PlayerInjury).where(PlayerInjury.player_id.in_(pids))):
        out[inj.player_id]["injuries"].append(rm.Injury(
            body_part=inj.body_part, injury_date=inj.injury_date, days_missed=inj.days_missed or 0,
            injury_type=inj.injury_type, side=inj.side,
            # no return date and no days missed = still injured (ongoing)
            return_date=inj.return_date or (date.max if inj.days_missed is None else None)))
    rows = db.execute(select(PlayerMatchStat, Match).join(Match, Match.match_id == PlayerMatchStat.match_id)
                      .where(PlayerMatchStat.player_id.in_(pids))).all()
    agg: dict = defaultdict(dict)   # several videos of one match -> one MatchLoad (max of each value)
    for s, m in rows:
        if m.match_date is None:
            continue
        a = agg[s.player_id].setdefault(m.match_id, {"match": m, "minutes": None, "km": None, "sprints": None})
        km = float(s.distance_km) if s.distance_km is not None else (
            float(s.distance_covered_meters) / 1000.0 if s.distance_covered_meters is not None else None)
        for k, v in (("minutes", s.minutes_played), ("km", km), ("sprints", s.sprint_count)):
            if v is not None:
                a[k] = max(a[k], v) if a[k] is not None else v
    for pid, by_match in agg.items():
        for mid, a in by_match.items():
            ml = rm.MatchLoad(a["match"].match_date, norm_surface(a["match"].surface), a["minutes"], a["km"], None,
                              a["sprints"])
            ml.match_id = mid
            ml.raw_surface = a["match"].surface or "unknown"
            out[pid]["matches"].append(ml)
    for pid in out:
        out[pid]["matches"].sort(key=lambda x: x.match_date)
    return out


# ------------------------------------------------------------------ serialisation
def factor_out(f: rm.Factor) -> dict:
    return {"key": f.key, "label": f.label, "multiplier": round(f.multiplier, 3), "basis": f.basis,
            "detail": f.detail, "citation": CITATIONS.get(f.key)}


def result_out(r: rm.RiskResult, **extra) -> dict:
    return {"as_of": r.as_of.isoformat(), "score": r.score, "band": r.band, "probability": r.probability,
            "multiplier": r.multiplier, "confidence": r.confidence, "status": r.status,
            "model_version": r.model_version, "factors": [factor_out(f) for f in r.factors],
            "notes": list(getattr(r, "notes", [])), **extra}


def top_factor(r: rm.RiskResult) -> Optional[str]:
    fs = [f for f in r.factors if f.multiplier > 1.0]
    return max(fs, key=lambda f: f.multiplier).label if fs else None


# ------------------------------------------------------------------ scoring
def player_report(player: Player, inputs: dict, today: date, next_date: Optional[date] = None,
                  next_surface: Optional[str] = None, minutes: float = 90.0) -> dict:
    inj, mts = inputs["injuries"], inputs["matches"]
    cur = rm.score_player(today, inj, mts, age_on(player.birth_date, today), None)
    previous = []
    for mt in mts:
        if mt.match_date > today:
            continue
        r = rm.score_player(mt.match_date, inj, mts, age_on(player.birth_date, mt.match_date), mt.surface,
                            mt.minutes or 90.0)
        previous.append({"match_id": mt.match_id, "as_of": mt.match_date.isoformat(), "score": r.score,
                         "band": r.band, "status": r.status, "surface": mt.raw_surface})
    nd = next_date or today
    proj = rm.project_next(today, nd, next_surface, inj, mts, age_on(player.birth_date, nd), minutes)
    return {"current": result_out(cur), "previous": previous,
            "projection": result_out(proj, next_surface=next_surface, minutes=minutes),
            "factors": [factor_out(f) for f in cur.factors], "confidence": cur.confidence,
            "has_injury_history": bool(inj), "matches_played": len(mts), "disclaimer": DISCLAIMER,
            "_cur": cur, "_proj": proj}


def roster_rows(db: Session, players: list[Player], today: date, next_date: Optional[date],
                next_surface: Optional[str]) -> list[dict]:
    inputs = load_inputs(db, [p.player_id for p in players])
    rows = []
    for p in players:
        rep = player_report(p, inputs[p.player_id], today, next_date, next_surface)
        cur, proj = rep["_cur"], rep["_proj"]
        rows.append({"player_id": p.player_id, "name": f"{p.first_name} {p.last_name}".strip(),
                     "number": p.jersey_number, "position": p.position, "current": cur.score,
                     "projected": proj.score, "delta": round(proj.score - cur.score, 1), "band": proj.band,
                     "current_band": cur.band, "top_factor": top_factor(proj), "confidence": proj.confidence,
                     "status": proj.status, "has_injury_history": rep["has_injury_history"],
                     "matches_played": rep["matches_played"]})
    return rows


# ------------------------------------------------------------------ persistence
def recompute(db: Session, player_ids: Iterable[int], today: Optional[date] = None) -> int:
    """Replace current + history snapshots of these players (encrypted). Skips silently without a key."""
    key = _key()
    pids = sorted(set(player_ids))
    if key is None or not pids:
        if key is None:
            log.warning("HEALTH_DATA_KEY missing: injury-risk snapshots not persisted")
        return 0
    today = today or date.today()
    players = db.scalars(select(Player).where(Player.player_id.in_(pids))).all()
    inputs = load_inputs(db, pids)
    db.execute(delete(PlayerRiskSnapshot).where(PlayerRiskSnapshot.player_id.in_(pids),
                                                PlayerRiskSnapshot.kind.in_(("current", "history"))))
    n = 0
    for p in players:
        inp = inputs[p.player_id]
        snaps = [(None, "current", rm.score_player(today, inp["injuries"], inp["matches"],
                                                   age_on(p.birth_date, today), None), None)]
        for mt in inp["matches"]:
            if mt.match_date <= today:
                snaps.append((mt.match_id, "history",
                              rm.score_player(mt.match_date, inp["injuries"], inp["matches"],
                                              age_on(p.birth_date, mt.match_date), mt.surface, mt.minutes or 90.0),
                              mt.raw_surface))
        for mid, kind, r, surf in snaps:
            db.add(PlayerRiskSnapshot(player_id=p.player_id, match_id=mid, kind=kind, as_of=r.as_of,
                                      next_surface=surf, score_enc=hc.encrypt_float(r.score, key), band=r.band,
                                      confidence=r.confidence,
                                      factors_enc=hc.encrypt_json([factor_out(f) for f in r.factors], key),
                                      model_version=r.model_version))
            n += 1
    db.flush()
    return n


def recompute_for_match(db: Session, match_id: int) -> int:
    pids = db.scalars(select(PlayerMatchStat.player_id).where(PlayerMatchStat.match_id == match_id)).all()
    return recompute(db, pids)
