"""Matches: list / detail / PATCH result, and match tags (tags live on the match)."""
from typing import Optional, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

import tagging
from database import get_db
from match_logic import effective_side, get_user_match, match_result, result_from_scores, user_match_ids_stmt
from models import Match, MatchVideo, User
from schemas import MatchOut, MatchPatchIn, TagIn, TagOut, TagsIn
from security import get_current_user

router = APIRouter(prefix="/api/matches", tags=["matches"])


def match_out(m: Match, user_id: int, video_count: int, tags: list[TagOut]) -> MatchOut:
    side = effective_side(m, user_id)
    ours, theirs = (m.home_team, m.away_team) if side == "home" else (m.away_team, m.home_team)
    return MatchOut(match_id=m.match_id, match_date=m.match_date, home_team=m.home_team.team_name,
                    away_team=m.away_team.team_name, home_team_id=m.home_team_id, away_team_id=m.away_team_id,
                    video_count=video_count, home_score=m.home_score, away_score=m.away_score, our_side=side,
                    our_team=ours.team_name, opponent=theirs.team_name, result=match_result(m, user_id),
                    created_at=m.created_at, tags=tags)


def _video_counts(db: Session, user_id: int, match_ids: list[int]) -> dict[int, int]:
    if not match_ids:
        return {}
    return dict(db.execute(select(MatchVideo.match_id, func.count(MatchVideo.video_id))
                           .where(MatchVideo.user_id == user_id, MatchVideo.match_id.in_(match_ids))
                           .group_by(MatchVideo.match_id)).all())


def _one(db: Session, user: User, m: Match) -> MatchOut:
    counts = _video_counts(db, user.user_id, [m.match_id])
    tags = tagging.tags_for_matches(db, user.user_id, [m.match_id])
    return match_out(m, user.user_id, counts.get(m.match_id, 0), tags.get(m.match_id, []))


@router.get("", response_model=list[MatchOut])
def list_matches(
    tag: list[str] = Query([], description="Filter key:value, repeatable: same key = OR, different keys = AND"),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> list[MatchOut]:
    """Matches where either team belongs to you, newest first, with your video count, score/result and tags."""
    q = (select(Match).options(joinedload(Match.home_team), joinedload(Match.away_team))
         .where(Match.match_id.in_(user_match_ids_stmt(user.user_id))))
    for clause in tagging.filter_clauses(user.user_id, Match.match_id, tag):
        q = q.where(clause)
    rows = db.scalars(q.order_by(Match.match_date.desc(), Match.match_id.desc())).all()
    ids = [m.match_id for m in rows]
    counts = _video_counts(db, user.user_id, ids)
    tags = tagging.tags_for_matches(db, user.user_id, ids)
    return [match_out(m, user.user_id, counts.get(m.match_id, 0), tags.get(m.match_id, [])) for m in rows]


@router.get("/{match_id}", response_model=MatchOut)
def get_match(match_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> MatchOut:
    return _one(db, user, get_user_match(db, user, match_id))


@router.patch("/{match_id}", response_model=MatchOut)
def patch_match(match_id: int, body: MatchPatchIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> MatchOut:
    """Set score / our_side / result. Scores go in pairs (both ints or both null). With scores, result is derived."""
    m = get_user_match(db, user, match_id)
    sent = body.model_fields_set
    if not sent:
        raise HTTPException(status_code=422, detail="Provide home_score/away_score, our_side and/or result")
    home = body.home_score if "home_score" in sent else m.home_score
    away = body.away_score if "away_score" in sent else m.away_score
    if (home is None) != (away is None):
        raise HTTPException(status_code=422, detail="home_score and away_score must be set together (or both null)")
    if "our_side" in sent:
        if body.our_side is None:
            raise HTTPException(status_code=422, detail="our_side must be 'home' or 'away'")
        m.our_side = body.our_side
    m.home_score, m.away_score = home, away
    derived = result_from_scores(home, away, effective_side(m, user.user_id))
    if derived is not None:
        if "result" in sent and body.result is not None and body.result != derived:
            raise HTTPException(status_code=422, detail=f"result {body.result} contradicts the score ({derived})")
        m.result = derived
    elif "result" in sent:
        m.result = body.result
    elif "home_score" in sent or "away_score" in sent:
        m.result = None  # scores cleared -> the old derived result no longer applies
    db.commit()
    return _one(db, user, m)


# ---------------------------------------------------------------- match tags
TagsBody = Union[TagsIn, list[TagIn]]


def tag_list(body) -> list[tuple[str, str]]:
    items = body.tags if isinstance(body, TagsIn) else body
    if len(items) > 50:
        raise HTTPException(status_code=422, detail="At most 50 tags per request")
    return tagging.normalize_tags(items)


def current_tags(db: Session, user_id: int, match_id: int) -> list[TagOut]:
    return tagging.tags_for_matches(db, user_id, [match_id]).get(match_id, [])


@router.get("/{match_id}/tags", response_model=list[TagOut])
def get_match_tags(match_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = get_user_match(db, user, match_id)
    return current_tags(db, user.user_id, m.match_id)


@router.post("/{match_id}/tags", response_model=list[TagOut])
def add_match_tags(match_id: int, body: TagsBody = Body(...), db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Add tags (keys/values are created if new). Body {tags:[{key,value}]} or a bare list. -> full tag set."""
    m = get_user_match(db, user, match_id)
    tagging.add_tags(db, user.user_id, m.match_id, tag_list(body))
    db.commit()
    return current_tags(db, user.user_id, m.match_id)


@router.put("/{match_id}/tags", response_model=list[TagOut])
def replace_match_tags(match_id: int, body: TagsBody = Body(...), db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """Replace the full tag set ([] clears it). -> full tag set."""
    m = get_user_match(db, user, match_id)
    tagging.replace_tags(db, user.user_id, m.match_id, tag_list(body))
    db.commit()
    return current_tags(db, user.user_id, m.match_id)


@router.delete("/{match_id}/tags", status_code=204)
def delete_match_tag(match_id: int, key: str = Query(...), value: Optional[str] = Query(None),
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    """Remove key=value (or every value of `key` if value is omitted). Idempotent: 204 even if absent."""
    m = get_user_match(db, user, match_id)
    tagging.remove_tags(db, user.user_id, m.match_id, key, value)
    db.commit()
    return Response(status_code=204)
