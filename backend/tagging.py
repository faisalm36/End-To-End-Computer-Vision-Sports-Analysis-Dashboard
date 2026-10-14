"""User-scoped tags. Tag keys/values are reusable per user; tags are attached to MATCHES (match_tags).
Tagging a video tags its match, and a video shows its match's tags.

Normalization: keys and values are trimmed with inner whitespace collapsed, stored with the FIRST-SEEN casing
("Weather") and matched case-insensitively everywhere ("weather" == "Weather", "raining" == "Raining").
Keys: 1-50 chars, no ':' (so ?tag=key:value is unambiguous) and no control characters. Values: 1-100 chars.
"""
import re
from collections import defaultdict
from typing import Iterable, Optional

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from sqlalchemy import and_, delete, exists, func, select
from sqlalchemy.orm import Session

from models import MatchTag, TagKey, TagValue
from schemas import TagIn, TagOut

KEY_RE = re.compile(r"^[^:\x00-\x1f\x7f]{1,50}$")
MAX_TAGS_PER_MATCH = 100


def norm_key(raw: str) -> str:
    k = " ".join(str(raw).split())
    if not KEY_RE.match(k):
        raise HTTPException(status_code=422, detail=f"Invalid tag key {raw!r}: 1-50 characters, no ':'")
    return k


def norm_value(raw: str) -> str:
    v = " ".join(str(raw).split())
    if not 1 <= len(v) <= 100:
        raise HTTPException(status_code=422, detail="Tag value must be 1-100 characters")
    return v


def _get_key(db: Session, user_id: int, key: str, create: bool) -> Optional[TagKey]:
    k = db.scalar(select(TagKey).where(TagKey.user_id == user_id, func.lower(TagKey.name) == key.lower()))
    if k is None and create:
        k = TagKey(user_id=user_id, name=key)
        db.add(k)
        db.flush()
    return k


def _get_value(db: Session, key: TagKey, value: str, create: bool) -> Optional[TagValue]:
    v = db.scalar(select(TagValue).where(TagValue.tag_key_id == key.tag_key_id,
                                         func.lower(TagValue.value) == value.lower()))
    if v is None and create:
        v = TagValue(tag_key_id=key.tag_key_id, value=value)
        db.add(v)
        db.flush()
    return v


def normalize_tags(tags: Iterable[TagIn]) -> list[tuple[str, str]]:
    seen, out = set(), []
    for t in tags:
        k, v = norm_key(t.key), norm_value(t.value)
        if (k.lower(), v.lower()) not in seen:
            seen.add((k.lower(), v.lower()))
            out.append((k, v))
    return out


def add_tags(db: Session, user_id: int, match_id: int, tags: list[tuple[str, str]]) -> None:
    for k, v in tags:
        key = _get_key(db, user_id, k, create=True)
        val = _get_value(db, key, v, create=True)
        if db.get(MatchTag, (match_id, val.tag_value_id)) is None:
            db.add(MatchTag(match_id=match_id, tag_value_id=val.tag_value_id))
    db.flush()
    n = db.scalar(select(func.count()).select_from(MatchTag).where(MatchTag.match_id == match_id))
    if n > MAX_TAGS_PER_MATCH:
        raise HTTPException(status_code=422, detail=f"At most {MAX_TAGS_PER_MATCH} tags per match")


def user_value_ids(user_id: int):
    return select(TagValue.tag_value_id).join(TagKey, TagKey.tag_key_id == TagValue.tag_key_id) \
        .where(TagKey.user_id == user_id)


def replace_tags(db: Session, user_id: int, match_id: int, tags: list[tuple[str, str]]) -> None:
    db.execute(delete(MatchTag).where(MatchTag.match_id == match_id,
                                      MatchTag.tag_value_id.in_(user_value_ids(user_id))))
    add_tags(db, user_id, match_id, tags)


def remove_tags(db: Session, user_id: int, match_id: int, key: str, value: Optional[str]) -> int:
    k = _get_key(db, user_id, norm_key(key), create=False)
    if k is None:
        return 0
    q = select(TagValue.tag_value_id).where(TagValue.tag_key_id == k.tag_key_id)
    if value is not None:
        q = q.where(func.lower(TagValue.value) == norm_value(value).lower())
    res = db.execute(delete(MatchTag).where(MatchTag.match_id == match_id, MatchTag.tag_value_id.in_(q)))
    return res.rowcount or 0


def tags_for_matches(db: Session, user_id: int, match_ids: Iterable[int]) -> dict[int, list[TagOut]]:
    ids = list(set(match_ids))
    out: dict[int, list[TagOut]] = defaultdict(list)
    if not ids:
        return out
    rows = db.execute(
        select(MatchTag.match_id, TagKey.name, TagValue.value)
        .join(TagValue, TagValue.tag_value_id == MatchTag.tag_value_id)
        .join(TagKey, TagKey.tag_key_id == TagValue.tag_key_id)
        .where(TagKey.user_id == user_id, MatchTag.match_id.in_(ids))
        .order_by(func.lower(TagKey.name), func.lower(TagValue.value))
    ).all()
    for mid, k, v in rows:
        out[mid].append(TagOut(key=k, value=v))
    return out


def parse_filter(raw: str) -> tuple[str, str]:
    """'weather:Raining' -> ('weather', 'Raining'); value may contain ':'."""
    if ":" not in raw:
        raise RequestValidationError([{"type": "value_error", "loc": ("query", "tag"), "input": raw,
                                       "msg": "tag filter must look like key:value"}])
    k, v = raw.split(":", 1)
    return norm_key(k), norm_value(v)


def has_tag_clause(user_id: int, match_id_col, key: str, values):
    """EXISTS clause: the match (match_id_col) carries user's tag key=<any of values> (case-insensitive)."""
    if isinstance(values, str):
        values = [values]
    return exists(
        select(MatchTag.match_id)
        .join(TagValue, TagValue.tag_value_id == MatchTag.tag_value_id)
        .join(TagKey, TagKey.tag_key_id == TagValue.tag_key_id)
        .where(and_(MatchTag.match_id == match_id_col, TagKey.user_id == user_id, func.lower(TagKey.name) == key.lower(),
                    func.lower(TagValue.value).in_([v.lower() for v in values])))
    )


def filter_clauses(user_id: int, match_id_col, raw_filters: Iterable[str]) -> list:
    """?tag=k:v (repeatable): same key = OR, different keys = AND."""
    by_key: dict[str, list[str]] = defaultdict(list)
    for raw in raw_filters or []:
        k, v = parse_filter(raw)
        by_key[k.lower()].append(v)
    return [has_tag_clause(user_id, match_id_col, k, vs) for k, vs in by_key.items()]


def parse_tags_json(raw: Optional[str]) -> list[TagIn]:
    """Upload form field `tags`: JSON '[{"key":..,"value":..}]' or '{"tags":[...]}'. ''/None -> []."""
    import json
    from pydantic import TypeAdapter, ValidationError
    if raw is None or not raw.strip():
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            data = data.get("tags", [])
        return TypeAdapter(list[TagIn]).validate_python(data)
    except (ValueError, ValidationError) as exc:
        raise RequestValidationError([{"type": "value_error", "loc": ("body", "tags"), "input": raw,
                                       "msg": f"tags must be a JSON list of {{key, value}} objects ({exc.__class__.__name__})"}])
