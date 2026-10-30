"""Roster injury-risk API (model rir-1.0, v0.9.0). Spec: docs/injury_risk_model.md.

GET    /api/players/{player_id}/injuries
POST   /api/players/{player_id}/injuries
PATCH  /api/players/{player_id}/injuries/{injury_id}
DELETE /api/players/{player_id}/injuries/{injury_id}
GET    /api/players/{player_id}/injury-risk?next_surface=&next_date=
GET    /api/players/{player_id}/injury-risk/projection?date=&surface=&minutes=
GET    /api/roster/injury-risk?team_id=&next_surface=&next_date=&sort=desc|asc
(PATCH /api/matches/{id} accepts `surface` and triggers a recompute - see routers/matches.py)
All: Bearer auth, owner-scoped (404 otherwise), {detail} errors, UTC 'Z' timestamps. Not medical advice.
"""
from datetime import date, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

import health_crypto as hc
import injury_service as svc
import risk_service as rs
from database import get_db
from models import Player, PlayerInjury, Team, User
from security import get_current_user
from timeutil import iso_utc

router = APIRouter(tags=["injury-risk"])

BodyPart = Literal["hamstring", "groin", "quadriceps", "calf", "ankle", "knee", "foot", "hip", "back", "shoulder",
                   "head", "other"]
InjuryType = Literal["muscle_strain", "ligament_sprain", "tendon", "fracture", "contusion", "concussion", "overuse",
                     "other"]
Side = Literal["left", "right", "both", "na"]
NextSurface = Literal["grass", "turf"]


class InjuryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body_part: BodyPart
    injury_type: InjuryType
    side: Side = "na"
    injury_date: date
    return_date: Optional[date] = None
    days_missed: Optional[int] = Field(None, ge=0, le=3650)
    is_recurrence: bool = False
    source: Literal["player", "staff"] = "player"
    notes: Optional[str] = Field(None, max_length=2000)


class InjuryPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body_part: Optional[BodyPart] = None
    injury_type: Optional[InjuryType] = None
    side: Optional[Side] = None
    injury_date: Optional[date] = None
    return_date: Optional[date] = None
    days_missed: Optional[int] = Field(None, ge=0, le=3650)
    is_recurrence: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _some(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")
        return self


def _validate_dates(injury_date: date, return_date: Optional[date], days_missed: Optional[int]) -> Optional[int]:
    if injury_date > date.today():
        raise HTTPException(status_code=422, detail="injury_date cannot be in the future")
    if return_date is not None:
        if return_date < injury_date:
            raise HTTPException(status_code=422, detail="return_date must be on or after injury_date")
        if days_missed is None:
            return (return_date - injury_date).days
    return days_missed


def _owned_player(db: Session, user: User, player_id: int) -> Player:
    p = db.scalar(select(Player).join(Team, Team.team_id == Player.team_id)
                  .where(Player.player_id == player_id, Team.user_id == user.user_id))
    if p is None:
        raise HTTPException(status_code=404, detail="Player not found")
    return p


def _injury_out(i: PlayerInjury) -> dict:
    end = i.return_date or (i.injury_date + timedelta(days=i.days_missed) if i.days_missed is not None else None)
    return {"injury_id": i.injury_id, "player_id": i.player_id, "body_part": i.body_part,
            "injury_type": i.injury_type, "side": i.side, "injury_date": i.injury_date.isoformat(),
            "return_date": i.return_date.isoformat() if i.return_date else None, "days_missed": i.days_missed,
            "is_recurrence": bool(i.is_recurrence), "source": i.source, "notes": svc.decrypt_notes(i.notes_enc),
            "active": end is None or end > date.today(),
            "created_at": iso_utc(i.created_at), "updated_at": iso_utc(i.updated_at)}


def _get_injury(db: Session, player: Player, injury_id: int) -> PlayerInjury:
    i = db.get(PlayerInjury, injury_id)
    if i is None or i.player_id != player.player_id:
        raise HTTPException(status_code=404, detail="Injury not found")
    return i


def _enc_notes(notes: Optional[str]) -> Optional[str]:
    try:
        return svc.encrypt_notes(notes)
    except hc.HealthKeyError as e:
        raise HTTPException(status_code=503, detail=f"Health data encryption is not configured: {e}") from None


# ------------------------------------------------------------------ injuries CRUD
@router.get("/api/players/{player_id}/injuries")
def list_injuries(player_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _owned_player(db, user, player_id)
    rows = db.scalars(select(PlayerInjury).where(PlayerInjury.player_id == p.player_id)
                      .order_by(PlayerInjury.injury_date.desc(), PlayerInjury.injury_id.desc())).all()
    return [_injury_out(i) for i in rows]


@router.post("/api/players/{player_id}/injuries", status_code=201)
def create_injury(player_id: int, body: InjuryIn, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    p = _owned_player(db, user, player_id)
    days = _validate_dates(body.injury_date, body.return_date, body.days_missed)
    i = PlayerInjury(player_id=p.player_id, user_id=user.user_id, body_part=body.body_part,
                     injury_type=body.injury_type, side=body.side, injury_date=body.injury_date,
                     return_date=body.return_date, days_missed=days, is_recurrence=body.is_recurrence,
                     source=body.source, notes_enc=_enc_notes(body.notes))
    db.add(i)
    db.flush()
    svc.recompute(db, [p.player_id])
    db.commit()
    db.refresh(i)
    return _injury_out(i)


@router.patch("/api/players/{player_id}/injuries/{injury_id}")
def update_injury(player_id: int, injury_id: int, body: InjuryPatchIn, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    p = _owned_player(db, user, player_id)
    i = _get_injury(db, p, injury_id)
    data = body.model_dump(exclude_unset=True)
    for k in ("body_part", "injury_type", "side", "injury_date", "is_recurrence"):
        if k in data and data[k] is None:
            raise HTTPException(status_code=422, detail=f"{k} cannot be null")
    inj_date = data.get("injury_date", i.injury_date)
    ret = data["return_date"] if "return_date" in data else i.return_date
    days = data["days_missed"] if "days_missed" in data else (None if "return_date" in data else i.days_missed)
    days = _validate_dates(inj_date, ret, days)
    for k in ("body_part", "injury_type", "side", "is_recurrence"):
        if k in data:
            setattr(i, k, data[k])
    i.injury_date, i.return_date, i.days_missed = inj_date, ret, days
    if "notes" in data:
        i.notes_enc = _enc_notes(data["notes"])
    db.flush()
    svc.recompute(db, [p.player_id])
    db.commit()
    db.refresh(i)
    return _injury_out(i)


@router.delete("/api/players/{player_id}/injuries/{injury_id}", status_code=204)
def delete_injury(player_id: int, injury_id: int, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    p = _owned_player(db, user, player_id)
    db.delete(_get_injury(db, p, injury_id))
    db.flush()
    svc.recompute(db, [p.player_id])
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------ scores
def _head(p: Player) -> dict:
    return {"player_id": p.player_id, "name": f"{p.first_name} {p.last_name}".strip(), "number": p.jersey_number,
            "position": p.position, "team_id": p.team_id, "birth_date": p.birth_date.isoformat() if p.birth_date else None}


def _clean(rep: dict) -> dict:
    return {k: v for k, v in rep.items() if not k.startswith("_")}


@router.get("/api/players/{player_id}/injury-risk")
def player_injury_risk(player_id: int, next_surface: Optional[NextSurface] = Query(None),
                       next_date: Optional[date] = Query(None), user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    p = _owned_player(db, user, player_id)
    today = date.today()
    if next_date is not None and next_date < today:
        raise HTTPException(status_code=422, detail="next_date cannot be in the past")
    rep = svc.player_report(p, svc.load_inputs(db, [p.player_id])[p.player_id], today, next_date, next_surface)
    return {"player": _head(p), **_clean(rep)}


@router.get("/api/players/{player_id}/injury-risk/projection")
def player_projection(player_id: int, date_: Optional[date] = Query(None, alias="date"),
                      surface: Optional[NextSurface] = Query(None),
                      minutes: float = Query(90.0, ge=1, le=130), user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    p = _owned_player(db, user, player_id)
    today = date.today()
    if date_ is not None and date_ < today:
        raise HTTPException(status_code=422, detail="date cannot be in the past")
    rep = svc.player_report(p, svc.load_inputs(db, [p.player_id])[p.player_id], today, date_, surface, minutes)
    return {"player": _head(p), "projection": rep["projection"], "disclaimer": svc.DISCLAIMER}


@router.get("/api/roster/injury-risk")
def roster_injury_risk(team_id: Optional[int] = Query(None), next_surface: Optional[NextSurface] = Query(None),
                       next_date: Optional[date] = Query(None), sort: str = Query("desc", pattern="^(desc|asc)$"),
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    today = date.today()
    if next_date is not None and next_date < today:
        raise HTTPException(status_code=422, detail="next_date cannot be in the past")
    q = select(Player).join(Team, Team.team_id == Player.team_id).where(Team.user_id == user.user_id)
    teams = db.scalars(select(Team).where(Team.user_id == user.user_id).order_by(Team.team_id)).all()
    if team_id is not None:
        if team_id not in {t.team_id for t in teams}:
            raise HTTPException(status_code=404, detail="Team not found")
        q = q.where(Player.team_id == team_id)
    players = [p for p in db.scalars(q.order_by(Player.player_id)).all() if not rs.is_placeholder(p, {})]
    rows = svc.roster_rows(db, players, today, next_date, next_surface)
    rows.sort(key=lambda r: (r["projected"], r["current"]), reverse=(sort == "desc"))
    return {"team_id": team_id, "teams": [{"team_id": t.team_id, "team_name": t.team_name} for t in teams],
            "as_of": today.isoformat(), "next_surface": next_surface,
            "next_date": (next_date or today).isoformat(), "model_version": svc.rm.MODEL_VERSION,
            "bands": {"low": [0, 25], "moderate": [25, 50], "high": [50, 100]},
            "players": rows, "disclaimer": svc.DISCLAIMER}
