"""Password hashing (bcrypt) and JWT access tokens (PyJWT)."""
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import User

# /docs "Authorize" posts an OAuth2 password form here (username = email).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")
oauth2_optional = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

BCRYPT_MAX_BYTES = 72  # bcrypt ignores/rejects anything past 72 bytes
_DUMMY_HASH = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt()).decode()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str | None) -> bool:
    pw = password.encode("utf-8")
    if len(pw) > BCRYPT_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(pw, (password_hash or _DUMMY_HASH).encode("utf-8")) and password_hash is not None
    except ValueError:  # malformed hash in DB (e.g. old seed placeholder)
        return False


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_thumbnail_token(user_id: int, video_id: int) -> str:
    """Short-lived token that ONLY unlocks one video's thumbnail (for <img src>, which can't send headers)."""
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "vid": video_id, "type": "thumb", "iat": now,
               "exp": now + timedelta(minutes=settings.THUMBNAIL_TOKEN_EXPIRE_MINUTES)}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def thumbnail_token_user(token: str, video_id: int) -> Optional[int]:
    try:
        p = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        if p.get("type") != "thumb" or int(p.get("vid", -1)) != video_id:
            return None
        return int(p["sub"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        return None


def create_media_token(user_id: int, scope: str, minutes: Optional[int] = None) -> str:
    """Short-lived token that ONLY unlocks one media resource, for <img>/<video> src (can't send headers).
    scopes: "source:<video_id>", "frame:<video_id>", "track:<track_id>". Not usable as a login (type != access)."""
    now = datetime.now(timezone.utc)
    ttl = settings.MEDIA_TOKEN_EXPIRE_MINUTES if minutes is None else minutes
    payload = {"sub": str(user_id), "scope": scope, "type": "media", "iat": now, "exp": now + timedelta(minutes=ttl)}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def media_token_user(token: str, scope: str) -> Optional[int]:
    """user_id if `token` is a valid, unexpired media token for exactly this scope, else None."""
    try:
        p = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        if p.get("type") != "media" or p.get("scope") != scope:
            return None
        return int(p["sub"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        return None


def user_from_bearer(token: Optional[str], db: Session) -> Optional[User]:
    """Like get_current_user but returns None instead of raising (for optional auth)."""
    if not token:
        return None
    try:
        return get_current_user(token, db)
    except HTTPException:
        return None


_credentials_error = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "access":  # e.g. a thumbnail token must not work as a login
            raise _credentials_error
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        raise _credentials_error
    user = db.get(User, user_id)
    if user is None:
        raise _credentials_error
    return user
