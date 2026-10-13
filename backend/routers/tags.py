"""User-scoped tag catalog for autocomplete: GET /api/tags, /api/tags/keys, /api/tags/values?key=."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import tagging
from database import get_db
from match_logic import user_match_ids_stmt
from models import MatchTag, TagKey, TagValue, User
from security import get_current_user

router = APIRouter(prefix="/api/tags", tags=["tags"])


def _value_rows(db: Session, user_id: int, key: Optional[str] = None):
    """(key, value, match_count) for every tag value of the user; count = the user's matches carrying it."""
    count = (select(func.count(MatchTag.match_id))
             .where(MatchTag.tag_value_id == TagValue.tag_value_id,
                    MatchTag.match_id.in_(user_match_ids_stmt(user_id)))
             .correlate(TagValue).scalar_subquery())
    q = (select(TagKey.name, TagValue.value, count)
         .join(TagValue, TagValue.tag_key_id == TagKey.tag_key_id)
         .where(TagKey.user_id == user_id))
    if key is not None:
        q = q.where(func.lower(TagKey.name) == tagging.norm_key(key).lower())
    return db.execute(q).all()


@router.get("")
def all_tags(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    """[{key, values:[{value, count}]}], keys A-Z, values by count desc. count = number of your matches tagged.
    Keys with no values yet are included with values: []."""
    grouped: dict[str, list] = {k: [] for k in db.scalars(select(TagKey.name).where(TagKey.user_id == user.user_id))}
    for k, v, n in _value_rows(db, user.user_id):
        grouped.setdefault(k, []).append({"value": v, "count": int(n or 0)})
    return [{"key": k, "values": sorted(vs, key=lambda x: (-x["count"], x["value"].lower()))}
            for k, vs in sorted(grouped.items(), key=lambda kv: kv[0].lower())]


@router.get("/keys")
def tag_keys(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    """[{key, value_count, match_count}] (match_count = matches with any value of that key)."""
    keys = db.scalars(select(TagKey).where(TagKey.user_id == user.user_id).order_by(TagKey.name)).all()
    out = []
    for k in keys:
        n_vals = db.scalar(select(func.count()).select_from(TagValue).where(TagValue.tag_key_id == k.tag_key_id))
        n_matches = db.scalar(
            select(func.count(func.distinct(MatchTag.match_id)))
            .join(TagValue, TagValue.tag_value_id == MatchTag.tag_value_id)
            .where(TagValue.tag_key_id == k.tag_key_id, MatchTag.match_id.in_(user_match_ids_stmt(user.user_id))))
        out.append({"key": k.name, "value_count": int(n_vals or 0), "match_count": int(n_matches or 0)})
    return out


@router.get("/values")
def tag_values(key: Optional[str] = Query(None, description="Only values of this key"),
               q: Optional[str] = Query(None, description="Case-insensitive prefix filter"),
               db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    """[{key, value, count}] sorted by count desc. Unknown key -> []."""
    rows = [{"key": k, "value": v, "count": int(n or 0)} for k, v, n in _value_rows(db, user.user_id, key)]
    if q:
        rows = [r for r in rows if r["value"].lower().startswith(q.strip().lower())]
    return sorted(rows, key=lambda r: (-r["count"], r["key"], r["value"].lower()))
