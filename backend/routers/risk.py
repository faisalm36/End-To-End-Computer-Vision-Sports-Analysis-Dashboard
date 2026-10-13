"""Injury-risk dashboard API (v0.7.0). Contract: sync/CONTRACT_risk.md.

GET    /api/roster/risk?team_id=&sort=desc|asc&match_id=
GET    /api/players/{player_id}/risk
POST   /api/uploads/csv            (multipart: file, team_id?, dry_run?)
GET    /api/uploads/csv
DELETE /api/uploads/csv/{upload_id}
All: Bearer auth, owner-scoped (404 otherwise), {detail} errors, UTC 'Z' timestamps, X-Response-Time-ms header.
"""
import csv
import io
import logging
import re
import time
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

import health_crypto as hc
import risk_service as rs
from config import settings
from database import get_db
from match_logic import get_user_match
from models import AthleteLog, CsvUpload, Player, PlayerMatchRisk, Team, User
from security import get_current_user
from timeutil import iso_utc, utcnow

log = logging.getLogger("risk")
router = APIRouter(tags=["risk"])


def _ready() -> bytes:
    try:
        return rs.ensure_ready()
    except rs.RiskUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from None


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000.0, 1)


def _num(v: float):
    return int(v) if float(v).is_integer() else v


def _owned_team(db: Session, user: User, team_id: int) -> Team:
    t = db.scalar(select(Team).where(Team.team_id == team_id, Team.user_id == user.user_id))
    if t is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return t


def _score_out(d: dict) -> dict:
    return {**d, "computed_at": iso_utc(d["computed_at"])}


def _player_head(p: Player, t: Team) -> dict:
    return {"player_id": p.player_id, "name": f"{p.first_name} {p.last_name}".strip(), "first_name": p.first_name,
            "last_name": p.last_name, "jersey_number": p.jersey_number, "position": p.position,
            "team": {"team_id": t.team_id, "team_name": t.team_name}}


# --------------------------------------------------------------------------- roster
@router.get("/api/roster/risk")
def roster_risk(team_id: int = Query(...), sort: str = Query("desc", pattern="^(desc|asc)$"),
                match_id: Optional[int] = Query(None), user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    t0 = time.perf_counter()
    team = _owned_team(db, user, team_id)
    if match_id is not None:
        get_user_match(db, user, match_id)
    key = _ready()
    players = db.scalars(select(Player).where(Player.team_id == team.team_id)).all()
    pids = [p.player_id for p in players]
    best: dict[int, PlayerMatchRisk] = {}
    if pids:
        q = select(PlayerMatchRisk).where(PlayerMatchRisk.player_id.in_(pids))
        if match_id is not None:
            q = q.where(PlayerMatchRisk.match_id == match_id, PlayerMatchRisk.source == "match")
        for r in db.scalars(q).all():
            if r.player_id not in best or rs.latest_key(r) > rs.latest_key(best[r.player_id]):
                best[r.player_id] = r
    out = []
    for p in players:
        score = rs.decode(best[p.player_id], key) if p.player_id in best else rs.no_data()
        out.append({**_player_head(p, team), **_score_out(score)})
    scored = [o for o in out if o["risk_percent"] is not None]
    unscored = [o for o in out if o["risk_percent"] is None]
    scored.sort(key=lambda o: (o["risk_percent"] if sort == "asc" else -o["risk_percent"], o["name"].lower()))
    unscored.sort(key=lambda o: o["name"].lower())
    from ml import scorer
    return {"team_id": team.team_id, "match_id": match_id, "sort": sort, "model_version": scorer.model_version(),
            "thresholds": {"red": _num(settings.RISK_RED_THRESHOLD), "yellow": _num(settings.RISK_YELLOW_THRESHOLD)},
            "generated_at": iso_utc(utcnow()), "latency_ms": _ms(t0),
            "players": scored + unscored}


@router.get("/api/players/{player_id}/risk")
def player_risk_history(player_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.execute(select(Player, Team).join(Team, Team.team_id == Player.team_id)
                     .where(Player.player_id == player_id, Team.user_id == user.user_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Player not found")
    p = row[0]
    key = _ready()
    rows = db.scalars(select(PlayerMatchRisk).where(PlayerMatchRisk.player_id == player_id)).all()
    rows = sorted(rows, key=lambda r: (r.score_date or date.min, r.risk_id), reverse=True)
    return {"player_id": p.player_id, "name": f"{p.first_name} {p.last_name}".strip(),
            "history": [_score_out(rs.decode(r, key)) for r in rows]}


# --------------------------------------------------------------------------- CSV upload
CANON = {  # canonical -> accepted normalised headers (lowercase, spaces/underscores/hyphens/punctuation removed)
    "date": {"date", "logdate", "sessiondate", "matchdate", "day"},
    "player_id": {"playerid", "athleteid"},
    "jersey_number": {"jerseynumber", "jersey", "jerseyno", "shirtnumber", "shirt", "number", "no"},
    "player": {"player", "name", "playername", "athlete", "athletename", "fullname"},
    "gps_distance": {"gpsdistance", "gpsdistancekm", "distance", "distancekm", "totaldistance", "totaldistancekm"},
    "gps_distance_m": {"gpsdistancem", "gpsdistancemeters", "gpsdistancemetres", "distancem", "distancemeters",
                       "distancemetres", "totaldistancem"},
    "heart_rate": {"heartrate", "hr", "avghr", "hravg", "heartrateavg", "avgheartrate", "averageheartrate",
                   "heartratebpm"},
    "heart_rate_max": {"heartratemax", "maxhr", "hrmax", "maxheartrate"},
    "minutes_played": {"minutesplayed", "minutes", "mins", "minsplayed", "minutesonpitch"},
    "sprints": {"sprints", "sprintcount", "numsprints", "sprintsn"},
    "top_speed_kmh": {"topspeedkmh", "topspeed", "maxspeed", "maxspeedkmh", "peakspeed", "peakspeedkmh"},
}
LOOKUP = {alias: canon for canon, aliases in CANON.items() for alias in aliases}
RANGES = {"gps_distance": (0, 30, "km"), "gps_distance_m": (0, 30000, "m"), "heart_rate": (30, 230, "bpm"),
          "heart_rate_max": (30, 230, "bpm"), "minutes_played": (0, 130, "min"), "sprints": (0, 300, ""),
          "top_speed_kmh": (0, 45, "km/h")}
CSV_TYPES = {"text/csv", "application/csv", "application/vnd.ms-excel", "text/plain", "text/x-csv",
             "application/x-csv", "text/comma-separated-values", "application/octet-stream", ""}


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (h or "").lower())


def _parse_date(s: str) -> Optional[date]:
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _name_key(s: str) -> str:
    s = (s or "").strip().casefold()
    if "," in s:  # "Last, First"
        last, _, first = s.partition(",")
        s = f"{first.strip()} {last.strip()}"
    return " ".join(s.split())


class _Roster:
    def __init__(self, players: list[Player], team_id: Optional[int]):
        self.by_id = {p.player_id: p for p in players}
        self.jersey = defaultdict(list)
        self.name = defaultdict(list)
        for p in players:
            if team_id is not None and p.team_id != team_id:
                continue
            if p.jersey_number is not None:
                self.jersey[p.jersey_number].append(p)
            self.name[_name_key(f"{p.first_name} {p.last_name}")].append(p)
        self.team_id = team_id

    def match(self, pid: Optional[int], jersey: Optional[int], name: Optional[str]) -> Optional[Player]:
        if pid is not None:
            p = self.by_id.get(pid)
            return p if p is not None and (self.team_id is None or p.team_id == self.team_id) else None
        if jersey is not None:
            c = self.jersey.get(jersey) or []
            if len(c) == 1:
                return c[0]
            if c:  # ambiguous across teams -> fall through to name
                pass
        if name:
            c = self.name.get(_name_key(name)) or []
            if len(c) == 1:
                return c[0]
        return None


def _bad(status: int, detail: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail, **extra})


@router.post("/api/uploads/csv", status_code=201)
async def upload_csv(file: UploadFile = File(...), team_id: Optional[int] = Form(None),
                     dry_run: bool = Form(False), user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    t0 = time.perf_counter()
    if team_id is not None:
        _owned_team(db, user, team_id)
    fname = (file.filename or "upload.csv")[:255]
    ctype = (file.content_type or "").split(";")[0].strip().lower()
    if not fname.lower().endswith(".csv") and ctype not in {"text/csv", "application/csv", "text/x-csv"}:
        return _bad(415, "File must be a .csv (text/csv)")
    if ctype not in CSV_TYPES:
        return _bad(415, f"Unsupported content type {ctype!r}; upload a .csv file")
    limit = settings.CSV_MAX_MB * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        return _bad(413, f"CSV larger than {settings.CSV_MAX_MB} MB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _bad(415, "CSV must be UTF-8 encoded")
    if not text.strip():
        return _bad(422, "empty file")
    key = _ready()
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except (StopIteration, csv.Error):
        return _bad(422, "empty file")
    cols: dict[str, int] = {}
    detected: dict[str, str] = {}
    for i, h in enumerate(header):
        c = LOOKUP.get(_norm(h))
        if c and c not in cols:
            cols[c], detected[c] = i, h
    missing = []
    if "date" not in cols:
        missing.append("date")
    if not ({"player_id", "jersey_number", "player"} & cols.keys()):
        missing.append("player_id|jersey_number|player")
    if missing:
        return _bad(422, "missing required column(s): " + ", ".join(missing), missing_columns=missing)

    raw_rows: list[tuple[int, list[str]]] = []
    try:
        for rec in reader:
            if not any((c or "").strip() for c in rec):
                continue
            raw_rows.append((reader.line_num, rec))
            if len(raw_rows) > settings.CSV_MAX_ROWS:
                return _bad(413, f"CSV has more than {settings.CSV_MAX_ROWS} data rows")
    except csv.Error as e:
        return _bad(422, f"malformed CSV near line {reader.line_num}: {e}")
    if not raw_rows:
        return _bad(422, "no data rows")

    players = db.scalars(select(Player).join(Team, Team.team_id == Player.team_id)
                         .where(Team.user_id == user.user_id)).all()
    roster = _Roster(players, team_id)
    errors, unmatched, good = [], [], []
    for line, rec in raw_rows:
        cell = lambda c: (rec[cols[c]].strip() if c in cols and cols[c] < len(rec) else "")  # noqa: E731
        errs = []

        def err(c, msg):
            errs.append({"row": line, "column": detected.get(c, c), "value": cell(c), "message": msg})

        d = _parse_date(cell("date")) if cell("date") else None
        if not cell("date"):
            err("date", "date is required")
        elif d is None:
            err("date", "invalid date (use YYYY-MM-DD or MM/DD/YYYY)")
        vals: dict = {}
        for c, (lo, hi, unit) in RANGES.items():
            s = cell(c)
            if not s:
                vals[c] = None
                continue
            try:
                x = float(s)
                if x != x:
                    raise ValueError
            except ValueError:
                err(c, "not a number")
                continue
            if not lo <= x <= hi:
                err(c, f"out of range ({lo}-{hi}{' ' + unit if unit else ''})")
                continue
            if c == "sprints" and not x.is_integer():
                err(c, "must be a whole number")
                continue
            vals[c] = x
        pid = jersey = None
        if cell("player_id"):
            try:
                pid = int(cell("player_id"))
            except ValueError:
                err("player_id", "not an integer")
        if cell("jersey_number"):
            try:
                jersey = int(float(cell("jersey_number")))
            except ValueError:
                err("jersey_number", "not an integer")
        ident = cell("player_id") or cell("jersey_number") or cell("player")
        if not ident:
            err(next(c for c in ("player_id", "jersey_number", "player") if c in cols), "player is required")
        if errs:
            errors.extend(errs)
            continue
        p = roster.match(pid, jersey, cell("player") or None)
        if p is None:
            unmatched.append({"row": line, "player": ident})
            continue
        km = vals["gps_distance"] if vals["gps_distance"] is not None else (
            None if vals["gps_distance_m"] is None else vals["gps_distance_m"] / 1000.0)
        good.append({"tmp": line, "player_id": p.player_id, "log_date": d, "gps_distance_km": km,
                     "minutes_played": vals["minutes_played"],
                     "sprints": None if vals["sprints"] is None else int(vals["sprints"]),
                     "top_speed_kmh": vals["top_speed_kmh"], "heart_rate": vals["heart_rate"],
                     "heart_rate_max": vals["heart_rate_max"]})
    invalid_rows = len({e["row"] for e in errors})
    names = {p.player_id: f"{p.first_name} {p.last_name}".strip() for p in players}
    affected = {g["player_id"] for g in good}
    upload_id = None
    if dry_run:
        rows = rs.compute(db, affected, extra_logs=good)
        by_line = {r["tmp"]: r for r in rows if r["source"] == "csv" and r["tmp"] is not None}
    else:
        up = CsvUpload(user_id=user.user_id, team_id=team_id, filename=fname, rows_total=len(raw_rows),
                       rows_valid=len(good), rows_invalid=invalid_rows, rows_unmatched=len(unmatched))
        db.add(up)
        db.flush()
        upload_id = up.upload_id
        line_of_log = {}
        for g in good:
            lg = AthleteLog(upload_id=up.upload_id, player_id=g["player_id"], log_date=g["log_date"],
                            source_row=g["tmp"], gps_distance_km=g["gps_distance_km"],
                            minutes_played=g["minutes_played"], sprints=g["sprints"], top_speed_kmh=g["top_speed_kmh"],
                            heart_rate_enc=hc.encrypt_float(g["heart_rate"], key),
                            heart_rate_max_enc=hc.encrypt_float(g["heart_rate_max"], key))
            db.add(lg)
            db.flush()
            line_of_log[lg.log_id] = g["tmp"]
        rows = rs.rescore_players(db, affected)
        db.commit()
        by_line = {line_of_log[r["log_id"]]: r for r in rows if r["source"] == "csv" and r["log_id"] in line_of_log}
    results = []
    for g in good:
        r = by_line.get(g["tmp"], {})
        results.append({"row": g["tmp"], "player_id": g["player_id"], "name": names.get(g["player_id"]),
                        "date": g["log_date"].isoformat(), "risk_percent": r.get("risk_percent"),
                        "level": r.get("level", "unknown"), "score_status": r.get("score_status", "no_data"),
                        "factors": r.get("factors", [])})
    body = {"upload_id": upload_id, "dry_run": dry_run, "filename": fname, "rows_total": len(raw_rows),
            "rows_valid": len(good), "rows_invalid": invalid_rows, "rows_unmatched": len(unmatched),
            "columns_detected": detected, "errors": errors, "unmatched": unmatched, "results": results,
            "latency_ms": _ms(t0)}
    log.info("csv upload user=%s rows=%d valid=%d dry_run=%s latency_ms=%.1f", user.user_id, len(raw_rows),
             len(good), dry_run, body["latency_ms"])
    return JSONResponse(status_code=200 if dry_run else 201, content=body)


@router.get("/api/uploads/csv")
def list_csv_uploads(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ups = db.scalars(select(CsvUpload).where(CsvUpload.user_id == user.user_id)
                     .order_by(CsvUpload.upload_id.desc())).all()
    return [{"upload_id": u.upload_id, "filename": u.filename, "rows_valid": u.rows_valid,
             "rows_invalid": u.rows_invalid, "created_at": iso_utc(u.created_at)} for u in ups]


@router.delete("/api/uploads/csv/{upload_id}", status_code=204)
def delete_csv_upload(upload_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    up = db.scalar(select(CsvUpload).where(CsvUpload.upload_id == upload_id, CsvUpload.user_id == user.user_id))
    if up is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    _ready()
    log_ids = select(AthleteLog.log_id).where(AthleteLog.upload_id == upload_id)
    affected = set(db.scalars(select(AthleteLog.player_id).where(AthleteLog.upload_id == upload_id)).all())
    db.execute(PlayerMatchRisk.__table__.delete().where(PlayerMatchRisk.log_id.in_(log_ids)))
    db.execute(AthleteLog.__table__.delete().where(AthleteLog.upload_id == upload_id))
    db.delete(up)
    db.flush()
    rs.rescore_players(db, affected)
    db.commit()
    return Response(status_code=204)
