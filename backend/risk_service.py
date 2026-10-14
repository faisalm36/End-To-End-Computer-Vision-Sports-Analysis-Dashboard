"""Injury-risk scoring service: gates, feature timelines, persistence (encrypted), and read helpers.

Every write path (ingest, backfill, CSV upload/delete) calls rescore_players(): it recomputes ALL risk rows of the
given players (ACWR depends on history, so a new/deleted session can change later scores), then replaces them.

Gates for CV rows (source 'match'), from the CV Engineer (see ml/README.md):
  (a) distance_valid not false (video meta / per-player) and distance_km not null
  (b) meta.calibration is a real custom file (not null/'none'/default_calibration.json)
  (c) visible_minutes >= 1 (exposure; never used as time on the pitch)
  (d) features are per-minute / per-90 rates over visible_minutes (ml/features.py)
  (e) placeholder players (no roster match) are never scored
Demo rows (adapter_source stub/seed, or no video) skip (a-calibration part) and (b) and carry data_quality 'demo'.
"""
import json
import logging
from collections import defaultdict
from datetime import date
from pathlib import PurePath
from typing import Iterable, Optional

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

import health_crypto as hc
import metrics_catalog as mc
from ml import features as F
from ml import scorer
from models import AthleteLog, Match, MatchVideo, Player, PlayerMatchRisk, PlayerMatchStat
from timeutil import utcnow

log = logging.getLogger("risk")

DEMO_ADAPTERS = {"stub", "seed"}
EMPTY_FEATURES = {k: None for k in F.DISPLAY_FEATURES}


class RiskUnavailable(RuntimeError):
    """Key or model missing/broken -> API answers 503 with this message."""


def ensure_ready() -> bytes:
    try:
        key = hc.parse_key(hc.settings.HEALTH_DATA_KEY)
    except hc.HealthKeyError as e:
        raise RiskUnavailable(f"Health data encryption is not configured: {e}") from None
    try:
        scorer.load()
    except scorer.RiskModelError as e:
        raise RiskUnavailable(f"Risk model unavailable: {e}") from None
    return key


# --------------------------------------------------------------------------- gates
def real_custom_calibration(cal) -> bool:
    if not isinstance(cal, str) or not cal.strip() or cal.strip().lower() in ("none", "null"):
        return False
    return PurePath(cal.strip()).name != "default_calibration.json"


def is_placeholder(p: Player, gate: dict) -> bool:
    if p.player_id in set(gate.get("placeholder_player_ids") or []):
        return True
    return p.first_name == "Unknown" and (p.position == "Unassigned" or (p.last_name or "").startswith(("#", "Track ")))


def gate_match_row(player: Player, video_id: Optional[int], meta: dict, v: dict) -> dict:
    """-> {status, note, data_quality, exposure, minutes_for_model}"""
    gate = meta.get("risk_gate") if isinstance(meta.get("risk_gate"), dict) else {}
    demo = video_id is None or meta.get("adapter_source") in DEMO_ADAPTERS
    failed, uncal = [], False
    if is_placeholder(player, gate):
        failed.append("no roster match (placeholder player)")
    if not demo:
        if not real_custom_calibration(meta.get("calibration")):
            failed.append("no custom pitch calibration")
            uncal = True
        if meta.get("distance_valid") is False or player.player_id in set(gate.get("distance_invalid_player_ids") or []):
            failed.append("distance_valid=false")
            uncal = True
    if v.get("distance_km") is None:
        failed.append("distance missing")
    vis = v.get("visible_minutes")
    exposure = vis if (vis is not None or not demo) else v.get("minutes_played")
    if exposure is None or exposure < F.MIN_EXPOSURE_MIN:
        failed.append("visible_minutes < 1" if not demo else "exposure minutes < 1")
    status = "scored" if not failed else "uncalibrated" if uncal else "insufficient_data"
    return {"status": status, "note": "; ".join(failed) or None,
            "data_quality": "demo" if demo else ("calibrated" if not uncal else None),
            "exposure": exposure, "minutes_for_model": v.get("minutes_played") if demo else None}


def gate_csv_row(lg: dict) -> dict:
    measured = [lg.get(k) for k in ("gps_distance_km", "heart_rate", "sprints", "top_speed_kmh")]
    if all(x is None for x in measured):
        return {"status": "insufficient_data", "note": "no load values (gps_distance, heart_rate, sprints, top_speed)"}
    return {"status": "scored", "note": None}


# --------------------------------------------------------------------------- compute
def _date_key(d: Optional[date]) -> date:
    return d or date.min


def compute(db: Session, player_ids: Iterable[int], extra_logs: Optional[list[dict]] = None) -> list[dict]:
    """Recompute every risk row of these players (no writes). extra_logs = unsaved CSV rows (dry run / preview):
    dicts {tmp, player_id, log_date, gps_distance_km, minutes_played, sprints, top_speed_kmh, heart_rate,
    heart_rate_max}. Returns plain dicts (see _row)."""
    key = ensure_ready()
    pids = sorted(set(player_ids))
    if not pids:
        return []
    players = {p.player_id: p for p in db.scalars(select(Player).where(Player.player_id.in_(pids))).all()}
    # ---- CSV logs (stored + extra), HR decrypted in memory only
    logs: list[dict] = []
    for i in range(0, len(pids), 500):
        for lg in db.scalars(select(AthleteLog).where(AthleteLog.player_id.in_(pids[i:i + 500]))).all():
            logs.append({"log_id": lg.log_id, "tmp": None, "player_id": lg.player_id, "log_date": lg.log_date,
                         "gps_distance_km": lg.gps_distance_km, "minutes_played": lg.minutes_played,
                         "sprints": lg.sprints, "top_speed_kmh": lg.top_speed_kmh,
                         "heart_rate": hc.decrypt_float(lg.heart_rate_enc, key),
                         "heart_rate_max": hc.decrypt_float(lg.heart_rate_max_enc, key), "order": lg.log_id})
    for n, e in enumerate(extra_logs or []):
        logs.append({**e, "log_id": None, "order": 10 ** 12 + n})
    logs.sort(key=lambda r: (r["player_id"], r["log_date"], r["order"]))
    hr_by_day: dict[tuple, tuple] = {}
    for r in logs:  # last log of the day wins
        if r.get("heart_rate") is not None or r.get("heart_rate_max") is not None:
            hr_by_day[(r["player_id"], r["log_date"])] = (r.get("heart_rate"), r.get("heart_rate_max"))
    # ---- match stats rows
    stats = []
    for i in range(0, len(pids), 500):
        stats += db.execute(select(PlayerMatchStat, Match.match_date).join(Match, Match.match_id == PlayerMatchStat.match_id)
                            .where(PlayerMatchStat.player_id.in_(pids[i:i + 500]))).all()
    stats.sort(key=lambda t: (t[0].player_id, _date_key(t[1]), t[0].stat_id))
    values = mc.load_rows(db, [s for s, _ in stats]) if stats else {}
    vids = {s.video_id for s, _ in stats if s.video_id is not None}
    metas = {}
    if vids:
        for vid, pm in db.execute(select(MatchVideo.video_id, MatchVideo.pipeline_meta).where(MatchVideo.video_id.in_(vids))):
            try:
                metas[vid] = json.loads(pm) if pm else {}
            except ValueError:
                metas[vid] = {}

    pending: list[tuple[dict, dict]] = []   # (row, model_features) to score in one batch
    rows: list[dict] = []
    hist: dict[tuple, list] = defaultdict(list)
    for s, mdate in stats:
        p = players.get(s.player_id)
        if p is None:
            continue
        raw = dict(values.get(s.stat_id, {}))
        for col in ("distance_covered_meters", "top_speed_kmh", "minutes_played", "sprint_count"):
            val = getattr(s, col)
            if val is not None:
                raw[col] = float(val)
        v = F.stat_values(raw)
        hr, hrmax = hr_by_day.get((s.player_id, mdate), (None, None))
        g = gate_match_row(p, s.video_id, metas.get(s.video_id, {}), v)
        row = _row(player_id=s.player_id, source="match", stat_id=s.stat_id, match_id=s.match_id,
                   video_id=s.video_id, score_date=mdate, gate=g, display=F.display_from_stat(v, hr, hrmax))
        if g["status"] == "scored":
            hk = (s.player_id, g["data_quality"])
            feats = F.match_features(v, g["exposure"], hist[hk], hr, g["minutes_for_model"])
            hist[hk].append(F.match_load(v, g["exposure"]))
            pending.append((row, feats))
        rows.append(row)
    for lg in logs:
        if lg["player_id"] not in players:
            continue
        g = gate_csv_row(lg)
        g.update({"data_quality": "csv"})
        row = _row(player_id=lg["player_id"], source="csv", log_id=lg["log_id"], tmp=lg.get("tmp"),
                   score_date=lg["log_date"], gate=g, display=F.display_from_log(lg))
        if g["status"] == "scored":
            hk = (lg["player_id"], "csv")
            feats = F.csv_features(lg, hist[hk])
            if F.csv_load(lg) is not None:
                hist[hk].append(F.csv_load(lg))
            pending.append((row, feats))
        rows.append(row)
    scored = scorer.score([f for _, f in pending])
    for (row, _), res in zip(pending, scored):
        row.update({"risk_percent": res["risk_percent"], "level": res["level"], "model_features": res["features"],
                    "contributions": res["contributions"], "factors": scorer.factors(res["contributions"])})
    return rows


def _row(*, player_id, source, gate, display, score_date, stat_id=None, log_id=None, match_id=None, video_id=None,
         tmp=None) -> dict:
    return {"player_id": player_id, "source": source, "stat_id": stat_id, "log_id": log_id, "tmp": tmp,
            "match_id": match_id, "video_id": video_id, "score_date": score_date, "risk_percent": None,
            "level": "unknown", "score_status": gate["status"], "score_note": gate.get("note"),
            "data_quality": gate.get("data_quality"), "model_version": scorer.model_version(),
            "features": display, "model_features": None, "contributions": [], "factors": []}


# --------------------------------------------------------------------------- persist
def persist(db: Session, player_ids: Iterable[int], rows: list[dict]) -> int:
    key = ensure_ready()
    pids = sorted(set(player_ids))
    for i in range(0, len(pids), 500):
        db.execute(delete(PlayerMatchRisk).where(PlayerMatchRisk.player_id.in_(pids[i:i + 500])))
    now = utcnow()
    batch = [{
        "player_id": r["player_id"], "source": r["source"], "stat_id": r["stat_id"], "log_id": r["log_id"],
        "match_id": r["match_id"], "video_id": r["video_id"], "score_date": r["score_date"],
        "risk_percent_enc": hc.encrypt_float(r["risk_percent"], key), "level": r["level"],
        "score_status": r["score_status"], "score_note": (r["score_note"] or None) and r["score_note"][:255],
        "data_quality": r["data_quality"], "model_version": r["model_version"],
        "details_enc": hc.encrypt_json({"features": r["features"], "model_features": r["model_features"],
                                        "contributions": r["contributions"], "factors": r["factors"]}, key),
        "computed_at": now} for r in rows if r.get("tmp") is None]
    for i in range(0, len(batch), 500):
        db.execute(insert(PlayerMatchRisk), batch[i:i + 500])
    return len(batch)


def rescore_players(db: Session, player_ids: Iterable[int]) -> list[dict]:
    """compute + persist (caller commits)."""
    pids = sorted(set(player_ids))
    rows = compute(db, pids)
    persist(db, pids, rows)
    return rows


def rescore_video(db: Session, video_id: int) -> int:
    pids = db.scalars(select(PlayerMatchStat.player_id).where(PlayerMatchStat.video_id == video_id)).all()
    rows = rescore_players(db, pids)
    return sum(r["score_status"] == "scored" for r in rows)


# --------------------------------------------------------------------------- read
def decode(r: PlayerMatchRisk, key: bytes) -> dict:
    """Stored row -> contract score fields (risk_percent onward)."""
    det = hc.decrypt_json(r.details_enc, key) if r.details_enc else {}
    return {"risk_percent": hc.decrypt_float(r.risk_percent_enc, key), "level": r.level,
            "score_status": r.score_status, "score_note": r.score_note, "data_quality": r.data_quality,
            "source": r.source, "match_id": r.match_id,
            "match_date": r.score_date.isoformat() if r.score_date else None, "video_id": r.video_id,
            "model_version": r.model_version, "computed_at": r.computed_at,
            "features": {**EMPTY_FEATURES, **(det.get("features") or {})}, "factors": det.get("factors") or []}


def no_data() -> dict:
    return {"risk_percent": None, "level": "unknown", "score_status": "no_data", "score_note": None,
            "data_quality": None, "source": None, "match_id": None, "match_date": None, "video_id": None,
            "model_version": None, "computed_at": None, "features": dict(EMPTY_FEATURES), "factors": []}


def latest_key(r: PlayerMatchRisk) -> tuple:
    """Latest = newest date among SCORED rows first (gated-out rows only if nothing scored); match beats csv on
    the same date; then newest row."""
    return (r.score_status == "scored", _date_key(r.score_date), r.source == "match", r.risk_id)
