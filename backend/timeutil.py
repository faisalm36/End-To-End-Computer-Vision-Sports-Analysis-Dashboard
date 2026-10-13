"""UTC time helpers.

Storage convention: every DATETIME column holds **naive UTC**. Python writes use utcnow(); MySQL sessions are set
to time_zone '+00:00' (database.py) so CURRENT_TIMESTAMP defaults are UTC too. API responses serialize datetimes
as ISO 8601 with a 'Z' suffix (see schemas.UTCDateTime). Plain dates (match_date) stay YYYY-MM-DD.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current UTC time as a naive datetime (what we store in DATETIME columns)."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def iso_utc(dt: datetime | None) -> str | None:
    """Naive values are UTC by convention; aware values are converted. -> '2026-09-30T21:20:19Z'."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat() + "Z"
