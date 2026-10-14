"""Match ownership, "our side" and W/D/L result rules (shared by videos, matches, insights).

Rule: the user's team in a match is the side whose team belongs to the user (teams.user_id). If the user owns
BOTH teams (the upload flow creates both under the user), matches.our_side decides (NULL = home).
result = derived from home_score/away_score when both are set; otherwise matches.result (set by hand) or null.
"""
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from models import Match, Team, User


def user_match_ids_stmt(user_id: int):
    home, away = aliased(Team), aliased(Team)
    return (select(Match.match_id)
            .join(home, home.team_id == Match.home_team_id)
            .join(away, away.team_id == Match.away_team_id)
            .where(or_(home.user_id == user_id, away.user_id == user_id)))


def owns_match(match: Optional[Match], user_id: int) -> bool:
    return match is not None and user_id in {match.home_team.user_id, match.away_team.user_id}


def get_user_match(db: Session, user: User, match_id: int) -> Match:
    m = db.get(Match, match_id)
    if not owns_match(m, user.user_id):
        raise HTTPException(status_code=404, detail="Match not found")
    return m


def effective_side(match: Match, user_id: int) -> str:
    home_mine = match.home_team.user_id == user_id
    away_mine = match.away_team.user_id == user_id
    if home_mine and not away_mine:
        return "home"
    if away_mine and not home_mine:
        return "away"
    return match.our_side or "home"


def result_from_scores(home: Optional[int], away: Optional[int], side: str) -> Optional[str]:
    if home is None or away is None:
        return None
    ours, theirs = (home, away) if side == "home" else (away, home)
    return "W" if ours > theirs else "L" if ours < theirs else "D"


def match_result(match: Match, user_id: int) -> Optional[str]:
    r = result_from_scores(match.home_score, match.away_score, effective_side(match, user_id))
    return r if r is not None else match.result


def our_team_id(match: Match, user_id: int) -> int:
    return match.home_team_id if effective_side(match, user_id) == "home" else match.away_team_id
