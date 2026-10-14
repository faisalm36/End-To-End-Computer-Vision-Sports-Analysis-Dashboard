"""Shared media helpers: auth for <img>/<video> URLs (Bearer OR a scoped ?token=) and single-range HTTP responses.

Used by GET /api/videos/{id}/source, /api/videos/{id}/frame, /api/tracks/{id}/frames and
/api/tracks/{id}/annotated.mp4. Tokens are short-lived media tokens (security.create_media_token) with one scope:
source:<video_id> | frame:<video_id> | track:<track_id>.
"""
import re
from pathlib import Path
from typing import Iterator, Optional

from fastapi import HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from security import media_token_user, user_from_bearer

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
CHUNK = 256 * 1024


def media_user(db: Session, bearer: Optional[str], token: Optional[str], scope: str) -> int:
    """user_id from a Bearer access token, else from a media token with exactly this scope; 401 otherwise."""
    user_id = None
    if bearer:
        u = user_from_bearer(bearer, db)
        user_id = u.user_id if u else None
    if user_id is None and token:
        user_id = media_token_user(token, scope)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    return user_id


def _iter_file(path: Path, start: int, length: int) -> Iterator[bytes]:
    with path.open("rb") as f:
        f.seek(start)
        left = length
        while left > 0:
            data = f.read(min(CHUNK, left))
            if not data:
                break
            left -= len(data)
            yield data


def ranged_file_response(request: Request, path: Path, media_type: str) -> Response:
    """Single-range RFC 7233 support: 206 + Content-Range, 416 + 'bytes */size' if unsatisfiable. Malformed or
    multi-range headers are ignored (200 full body), as the RFC allows. If-Range with a stale ETag = full body.
    HEAD returns headers only."""
    st = path.stat()
    size = st.st_size
    etag = f'"{st.st_mtime_ns:x}-{size:x}"'
    headers = {"Accept-Ranges": "bytes", "ETag": etag, "Cache-Control": "private, max-age=300",
               "Content-Type": media_type}
    rng = request.headers.get("range")
    if_range = request.headers.get("if-range")
    if rng and if_range and if_range.strip() != etag:
        rng = None  # resource changed: send it whole
    start, end = 0, size - 1
    status_code = 200
    if rng:
        m = _RANGE.match(rng.strip().replace(" ", ""))
        if m and (m.group(1) or m.group(2)):
            a, b = m.group(1), m.group(2)
            if a == "":                      # suffix: last N bytes
                n = int(b)
                if n == 0 or size == 0:
                    return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
                start, end = max(0, size - n), size - 1
            else:
                start = int(a)
                end = min(int(b), size - 1) if b else size - 1
                if start >= size or (b and int(b) < start):
                    return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
            status_code = 206
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    length = max(0, end - start + 1)
    headers["Content-Length"] = str(length)
    if request.method == "HEAD":
        return Response(status_code=status_code, headers=headers)
    return StreamingResponse(_iter_file(path, start, length), status_code=status_code, headers=headers,
                             media_type=media_type)
