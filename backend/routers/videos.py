"""Video upload + processing status. All routes require a bearer token and are scoped to the current user."""
import json
import logging
import shutil
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import (APIRouter, BackgroundTasks, Body, Depends, File, Form, HTTPException, Query, Request, Response,
                     UploadFile, status)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, joinedload

from config import BASE_DIR, settings
from database import get_db
from models import (Match, MatchTag, MatchVideo, Player, PlayerMatchStat, PlayerTrack, Team, User,
                    VideoPlayerOverride)
from pipeline import effective_speed_thresholds, process_video
import metrics_catalog as mc
import tagging
import tracking
from match_logic import match_result
from routers.matches import current_tags, tag_list, TagsBody
from schemas import MatchSummary, PlayerStatMetricsOut, TagOut, VideoDetailOut, VideoOut, VideoPlayerPatchIn
from stats import wants_metrics
from media import media_user, ranged_file_response
from security import (create_media_token, create_thumbnail_token, get_current_user, oauth2_optional,
                      thumbnail_token_user, user_from_bearer)
from stats import aggregate_player_stats, has_overrides_table

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/videos", tags=["videos"])

ALLOWED_CONTENT_TYPES = {
    "video/mp4", "video/quicktime", "video/x-msvideo", "video/avi", "video/msvideo",
    "video/x-matroska", "video/mkv",
    "application/octet-stream",  # curl / some browsers send this; the magic-byte sniff still applies
}
CHUNK = 1024 * 1024


def _sniff_ok(head: bytes, ext: str) -> bool:
    """Cheap container signature check so a renamed .txt/.exe isn't accepted as video."""
    if ext in {"mp4", "mov"}:
        return head[4:8] in {b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot"}
    if ext == "avi":
        return head[:4] == b"RIFF" and head[8:12] == b"AVI "
    if ext == "mkv":
        return head[:4] == b"\x1a\x45\xdf\xa3"
    return False


def _parse_meta(raw: Optional[str]) -> Optional[dict]:
    if not raw:
        return None
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {"value": val}
    except ValueError:
        return {"raw": raw}


def _abs(path_str: Optional[str]) -> Optional[Path]:
    if not path_str:
        return None
    p = Path(path_str)
    return p if p.is_absolute() else BASE_DIR / p


def to_video_out(v: MatchVideo, detail: bool = False, tags: Optional[list[TagOut]] = None) -> VideoOut:
    m = v.match
    meta = _parse_meta(v.pipeline_meta)
    duration = v.duration_seconds
    if duration is None and isinstance(meta, dict):
        duration = meta.get("duration_s")
    thumb = _abs(v.thumbnail_path)
    thumbnail_url = None
    if thumb is not None and thumb.is_file() and v.user_id is not None:
        thumbnail_url = f"/api/videos/{v.video_id}/thumbnail?token={create_thumbnail_token(v.user_id, v.video_id)}"
    src = _abs(v.file_path)
    source_url = None
    if src is not None and src.is_file() and v.user_id is not None:
        source_url = f"/api/videos/{v.video_id}/source?token={create_media_token(v.user_id, f'source:{v.video_id}')}"
    result = match_result(m, v.user_id) if (m is not None and v.user_id is not None) else None
    data = dict(
        id=v.video_id,
        video_id=v.video_id,
        match_id=v.match_id,
        title=v.title,
        file_name=v.file_name,
        match_date=m.match_date if m else None,
        home_team=m.home_team.team_name if m else None,
        away_team=m.away_team.team_name if m else None,
        status=v.processing_status,
        stage=v.stage or "queued",
        progress=v.progress or 0,
        error_message=v.error_message,
        error=v.error_message,
        created_at=v.uploaded_at,
        uploaded_at=v.uploaded_at,
        processed_at=v.processed_at,
        fps=v.fps,
        video_type=v.video_type or "tactical_cam",
        resolution=v.resolution,
        duration_seconds=float(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None,
        thumbnail_url=thumbnail_url,
        source_url=source_url,
        match=MatchSummary(
            match_id=m.match_id, match_date=m.match_date,
            home_team=m.home_team.team_name, away_team=m.away_team.team_name,
            home_score=m.home_score, away_score=m.away_score,
            result=result,
        ) if m else None,
        result=result,
        tags=tags or [],
    )
    if detail:
        return VideoDetailOut(**data, pipeline_meta=meta)
    return VideoOut(**data)


def _get_or_create_team(db: Session, user: User, name: str) -> Team:
    name = name.strip()
    team = db.scalar(
        select(Team).where(Team.user_id == user.user_id, func.lower(Team.team_name) == name.lower())
    )
    if team is None:
        team = Team(user_id=user.user_id, team_name=name[:100])
        db.add(team)
        db.flush()
    return team


def _resolve_match(
    db: Session, user: User, match_id: Optional[int], match_date: Optional[date],
    home_team: Optional[str], away_team: Optional[str],
) -> Match:
    if match_id is not None:
        match = db.get(Match, match_id)
        owns = match is not None and user.user_id in {match.home_team.user_id, match.away_team.user_id}
        if not owns:
            raise HTTPException(status_code=404, detail="Match not found")
        return match
    if not (match_date and home_team and home_team.strip() and away_team and away_team.strip()):
        raise HTTPException(status_code=422, detail="Provide match_id, or match_date + home_team + away_team")
    if home_team.strip().lower() == away_team.strip().lower():
        raise HTTPException(status_code=422, detail="home_team and away_team must differ")
    home = _get_or_create_team(db, user, home_team)
    away = _get_or_create_team(db, user, away_team)
    match = db.scalar(select(Match).where(
        Match.home_team_id == home.team_id, Match.away_team_id == away.team_id, Match.match_date == match_date
    ))
    if match is None:
        match = Match(home_team_id=home.team_id, away_team_id=away.team_id, match_date=match_date)
        db.add(match)
        db.flush()
    return match


def _coerce_match_id(raw: Optional[str]) -> Optional[int]:
    """Multipart fields are strings: '12' -> 12; ''/'null'/'undefined'/'none' -> None; anything else -> 422."""
    if raw is None:
        return None
    s = raw.strip()
    if s.lower() in ("", "null", "undefined", "none"):
        return None
    if not s.isascii() or not s.isdigit() or int(s) <= 0:
        raise RequestValidationError([{"type": "int_parsing", "loc": ("body", "match_id"),
                                       "msg": "match_id must be a positive integer", "input": raw}])
    return int(s)


def not_ready_response(v: MatchVideo) -> Optional[JSONResponse]:
    """409 body shared by /stats and /heatmap until the video is done."""
    if v.processing_status == "done":
        return None
    detail = "Video processing failed" if v.processing_status == "failed" else "Video not processed yet"
    return JSONResponse(status_code=409, content={
        "detail": detail, "status": v.processing_status, "stage": v.stage, "progress": v.progress,
        "error_message": v.error_message if v.processing_status == "failed" else None,
    })


def _get_user_video(db: Session, user: User, video_id: int) -> MatchVideo:
    v = db.scalar(
        select(MatchVideo).options(joinedload(MatchVideo.match))
        .where(MatchVideo.video_id == video_id, MatchVideo.user_id == user.user_id)
    )
    if v is None:  # same 404 whether it doesn't exist or belongs to someone else
        raise HTTPException(status_code=404, detail="Video not found")
    return v


@router.post("", response_model=VideoDetailOut, status_code=status.HTTP_202_ACCEPTED)
def upload_video(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="mp4 / mov / avi / mkv"),
    title: Optional[str] = Form(None, max_length=255),
    match_date: Optional[date] = Form(None, description="YYYY-MM-DD"),
    home_team: Optional[str] = Form(None, max_length=100),
    away_team: Optional[str] = Form(None, max_length=100),
    our_side: Optional[str] = Form(None, description="'home' | 'away': which team is yours (for W/D/L) "
                                                    "when both teams are yours; default home"),
    video_type: Optional[str] = Form(None, description="tactical_cam | broadcast | endzone_cam (default tactical_cam)"),
    tags: Optional[str] = Form(None, description='Optional JSON: [{"key":"weather","value":"Raining"}] (tags the match)'),
    match_id: Optional[str] = Form(None, description="Attach to an existing match instead (integer; "
                                   "multipart sends it as a string, '' / 'null' / 'undefined' = not given)"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> VideoOut:
    match_id_int = _coerce_match_id(match_id)
    tag_items = tagging.normalize_tags(tagging.parse_tags_json(tags))
    our_side = (our_side or "").strip().lower() or None
    if our_side not in (None, "home", "away"):
        raise RequestValidationError([{"type": "literal_error", "loc": ("body", "our_side"), "input": our_side,
                                       "msg": "our_side must be 'home' or 'away'"}])
    VIDEO_TYPES = ("tactical_cam", "broadcast", "endzone_cam")
    vt = (video_type or "").strip().lower() or "tactical_cam"
    if vt not in VIDEO_TYPES:
        raise RequestValidationError([{"type": "literal_error", "loc": ("body", "video_type"), "input": video_type,
                                       "msg": "video_type must be tactical_cam | broadcast | endzone_cam"}])
    # 1. cheap checks first
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.max_upload_bytes + 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File too large (max {settings.MAX_UPLOAD_MB} MB)")
    original = Path(file.filename or "").name
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in settings.allowed_video_extensions:
        raise HTTPException(status_code=415, detail=f"Unsupported file type .{ext or '?'}; "
                            f"allowed: {', '.join(sorted(settings.allowed_video_extensions))}")
    ctype = (file.content_type or "application/octet-stream").split(";")[0].strip().lower()
    if ctype not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported content type {ctype}")

    match = _resolve_match(db, user, match_id_int, match_date, home_team, away_team)

    # 2. stream to disk under a random name, enforcing the size cap
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / f"{uuid.uuid4().hex}.{ext}"
    size = 0
    head = b""
    try:
        with dest.open("wb") as out:
            while chunk := file.file.read(CHUNK):
                if not head:
                    head = chunk[:16]
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail=f"File too large (max {settings.MAX_UPLOAD_MB} MB)")
                out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="Empty file")
        if not _sniff_ok(head, ext):
            raise HTTPException(status_code=415, detail=f"File content does not look like a .{ext} video")
    except BaseException:
        dest.unlink(missing_ok=True)
        db.rollback()
        raise

    # 3. DB row + background processing
    try:
        stored_path = str(dest.resolve().relative_to(BASE_DIR))
    except ValueError:
        stored_path = str(dest.resolve())
    video = MatchVideo(
        match_id=match.match_id, user_id=user.user_id,
        title=(title or original)[:255], file_name=original[:255] or dest.name,
        file_path=stored_path, processing_status="queued", video_type=vt,
    )
    db.add(video)
    if our_side:
        match.our_side = our_side
    if tag_items:
        tagging.add_tags(db, user.user_id, match.match_id, tag_items)
    db.commit()
    background_tasks.add_task(process_video, video.video_id)
    return _out(db, user, _get_user_video(db, user, video.video_id), detail=True)


def _out(db: Session, user: User, v: MatchVideo, detail: bool = True) -> VideoOut:
    return to_video_out(v, detail=detail, tags=current_tags(db, user.user_id, v.match_id))


@router.get("", response_model=list[VideoOut])
def list_videos(
    tag: list[str] = Query([], description="Filter by the match's tags, key:value, repeatable: same key = OR, "
                                           "different keys = AND, e.g. ?tag=weather:Raining&tag=pitch:Turf"),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> list[VideoOut]:
    q = (select(MatchVideo).options(joinedload(MatchVideo.match))
         .where(MatchVideo.user_id == user.user_id))
    for clause in tagging.filter_clauses(user.user_id, MatchVideo.match_id, tag):
        q = q.where(clause)
    rows = db.scalars(q.order_by(MatchVideo.uploaded_at.desc(), MatchVideo.video_id.desc())).unique().all()
    tags = tagging.tags_for_matches(db, user.user_id, [v.match_id for v in rows])
    # bare array (no pipeline_meta; see GET /api/videos/{id})
    return [to_video_out(v, tags=tags.get(v.match_id, [])) for v in rows]


@router.get("/{video_id}", response_model=VideoDetailOut)
def get_video(video_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> VideoOut:
    return _out(db, user, _get_user_video(db, user, video_id), detail=True)


@router.get("/{video_id}/stats", response_model=list[PlayerStatMetricsOut], response_model_exclude_unset=True,
            responses={409: {"description": "Video not processed yet / processing failed"}})
def video_stats(video_id: int,
                include: Optional[str] = Query(None, description="'metrics' adds metrics {key: value|null} + avg_position"),
                metrics: Optional[str] = Query(None, description="Comma-separated metric keys (default: all)"),
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Same shape as /api/players/stats, for the stats produced from THIS video.
    409 {"detail", "status", "stage", "progress", "error_message"} until status is done; [] if done with no rows."""
    v = _get_user_video(db, user, video_id)
    if (resp := not_ready_response(v)) is not None:
        return resp
    return _video_stat_rows(db, v, include_metrics=wants_metrics(include), metric_keys=mc.parse_keys(metrics))


def _video_stat_rows(db: Session, v: MatchVideo, include_metrics: bool = False,
                     metric_keys: Optional[list[str]] = None) -> list[PlayerStatMetricsOut]:
    rows = aggregate_player_stats(db, video_id=v.video_id, include_metrics=include_metrics,
                                  metric_keys=metric_keys, flat=True)
    # from this video's meta.json; missing keys (seeded rows, older pipelines) fall back to the CV defaults
    thresholds = effective_speed_thresholds(_parse_meta(v.pipeline_meta))
    for r in rows:
        r.speed_thresholds = thresholds
    return rows


@router.patch("/{video_id}/players/{player_id}", response_model=PlayerStatMetricsOut,
              response_model_exclude_unset=True,
              responses={404: {"description": "Video not found / player not in this video"},
                         409: {"description": "Video not processed yet, or the jersey is taken in this video"},
                         503: {"description": "Migration 007 not run yet"}})
def update_video_player(video_id: int, player_id: int, body: VideoPlayerPatchIn = Body(...),
                        db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Owner only. Set the player's jersey number FOR THIS VIDEO (0-99, or null = no number), e.g. to fix OCR.
    Stored per video in video_player_overrides; the roster (players.jersey_number) and other videos are unchanged.
    Returns the player's row in the GET /api/videos/{id}/stats shape."""
    v = _get_user_video(db, user, video_id)
    if (resp := not_ready_response(v)) is not None:
        return resp
    in_video = db.scalar(select(func.count()).select_from(PlayerMatchStat).where(
        PlayerMatchStat.video_id == v.video_id, PlayerMatchStat.player_id == player_id))
    player = db.get(Player, player_id) if in_video else None
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found in this video")
    if not has_overrides_table(db):
        raise HTTPException(status_code=503, detail="Per-video player edits need migrations/007_video_player_overrides.sql")
    new = body.jersey_number
    if new is not None:  # one shirt number per team per video
        current = {r.player_id: r.jersey_number for r in _video_stat_rows(db, v)}
        mates = db.scalars(select(Player).where(Player.team_id == player.team_id,
                                                Player.player_id.in_(list(current)),
                                                Player.player_id != player_id)).all()
        clash = next((p for p in mates if current.get(p.player_id) == new), None)
        if clash is not None:
            raise HTTPException(status_code=409, detail=f"Jersey #{new} is already used by "
                                                        f"{clash.first_name} {clash.last_name} in this video")
    row = db.get(VideoPlayerOverride, (v.video_id, player_id))
    if row is None:
        db.add(VideoPlayerOverride(video_id=v.video_id, player_id=player_id, jersey_number=new))
    else:
        row.jersey_number = new
    db.commit()
    return next(r for r in _video_stat_rows(db, v) if r.player_id == player_id)


@router.get("/{video_id}/thumbnail", response_class=FileResponse,
            responses={200: {"content": {"image/jpeg": {}}}, 404: {"description": "No thumbnail"}})
def video_thumbnail(
    video_id: int,
    token: Optional[str] = Query(None, description="Thumbnail token from thumbnail_url (for <img src>)"),
    bearer: Optional[str] = Depends(oauth2_optional),
    db: Session = Depends(get_db),
):
    """Auth: `Authorization: Bearer <access token>` OR the `?token=` embedded in `thumbnail_url`
    (scoped to this one video, short-lived). Access tokens are NOT accepted in the query string."""
    user_id = None
    if bearer:
        u = user_from_bearer(bearer, db)
        user_id = u.user_id if u else None
    if user_id is None and token:
        user_id = thumbnail_token_user(token, video_id)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    v = db.scalar(select(MatchVideo).where(MatchVideo.video_id == video_id, MatchVideo.user_id == user_id))
    thumb = _abs(v.thumbnail_path) if v else None
    if thumb is None or not thumb.is_file():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(thumb, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


VIDEO_TYPES = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo",
               ".mkv": "video/x-matroska", ".webm": "video/webm"}


@router.head("/{video_id}/source", include_in_schema=False)
@router.get("/{video_id}/source", response_class=Response,
            responses={200: {"content": {"video/mp4": {}}}, 206: {"description": "Partial content (Range)"},
                       401: {"description": "No/invalid/expired auth"}, 404: {"description": "Video not found"},
                       416: {"description": "Range not satisfiable"}})
def video_source(video_id: int, request: Request,
                 token: Optional[str] = Query(None, description="Media token from source_url (for <video src>)"),
                 bearer: Optional[str] = Depends(oauth2_optional), db: Session = Depends(get_db)):
    """The original uploaded file (for the live canvas overlay). Auth: Bearer, or the `?token=` in `source_url`
    (scoped to this video, short-lived; re-fetch the video for a fresh URL). Full HTTP Range support (206/416,
    Accept-Ranges, ETag, If-Range) and HEAD. Any processing status."""
    user_id = media_user(db, bearer, token, f"source:{video_id}")
    v = db.scalar(select(MatchVideo).where(MatchVideo.video_id == video_id, MatchVideo.user_id == user_id))
    if v is None:
        raise HTTPException(status_code=404, detail="Video not found")
    src = _abs(v.file_path)
    if src is None or not src.is_file():
        raise HTTPException(status_code=404, detail="Video file missing on the server")
    media_type = VIDEO_TYPES.get(Path(v.file_name or src.name).suffix.lower()) or \
        VIDEO_TYPES.get(src.suffix.lower(), "video/mp4")
    return ranged_file_response(request, src, media_type)


@router.delete("/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_video(video_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    """Owner only. Deletes the row (DB cascades player_match_stats + tracking_detections + per-video player
    overrides + player tracks), the uploaded file, thumbnail, cv_outputs/video_<id>/, cached frames
    (cv_outputs/frames/video_<id>/), tracking outputs (cv_outputs/track_<track_id>/) and this video's per-track
    placeholder players.
    Tags live on the match: if this was the match's last video AND the match has no other stats (e.g. legacy rows
    without a video), your tags on that match are removed too. The match itself (date, teams, score/result) is
    kept, as before. Allowed while processing: the background task notices the row is gone and stops."""
    v = _get_user_video(db, user, video_id)
    files = [_abs(v.file_path), _abs(v.thumbnail_path)]
    team_ids = [v.match.home_team_id, v.match.away_team_id] if v.match else []
    match_id = v.match_id
    if has_overrides_table(db):  # FK cascades too; explicit for connections without FK enforcement
        db.execute(delete(VideoPlayerOverride).where(VideoPlayerOverride.video_id == video_id))
    track_dirs = []
    if tracking.has_track_table(db):  # player tracks (migration 008): rows cascade; their files go below
        for tr in db.scalars(select(PlayerTrack).where(PlayerTrack.video_id == video_id)).all():
            track_dirs.append(tracking.absolute(tr.output_dir) or tracking.job_dir(tr.track_id))
            track_dirs.append(tracking.job_dir(tr.track_id))
        db.execute(delete(PlayerTrack).where(PlayerTrack.video_id == video_id))
    db.delete(v)
    db.flush()
    others = db.scalar(select(func.count()).select_from(MatchVideo).where(MatchVideo.match_id == match_id))
    stats_left = db.scalar(select(func.count()).select_from(PlayerMatchStat).where(
        PlayerMatchStat.match_id == match_id, PlayerMatchStat.video_id.is_distinct_from(video_id)))
    if not others and not stats_left:
        db.execute(delete(MatchTag).where(MatchTag.match_id == match_id,
                                          MatchTag.tag_value_id.in_(tagging.user_value_ids(user.user_id))))
    if team_ids:  # "Unknown Track N (video <id>)" placeholders only make sense for this video
        for p in db.scalars(select(Player).where(
            Player.team_id.in_(team_ids), Player.first_name == "Unknown",
            Player.last_name.like(f"% (video {video_id})"),
        )).all():
            db.delete(p)
    db.commit()
    for f in files:
        if f is not None:
            try:
                f.unlink(missing_ok=True)
            except OSError:
                log.warning("could not delete %s", f)
    shutil.rmtree(Path(settings.CV_OUTPUT_DIR) / f"video_{video_id}", ignore_errors=True)
    shutil.rmtree(tracking.frames_dir(video_id), ignore_errors=True)
    for d in track_dirs:
        shutil.rmtree(d, ignore_errors=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- video tags (= the video's match tags)
@router.get("/{video_id}/tags", response_model=list[TagOut])
def get_video_tags(video_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    v = _get_user_video(db, user, video_id)
    return current_tags(db, user.user_id, v.match_id)


@router.post("/{video_id}/tags", response_model=VideoDetailOut)
def add_video_tags(video_id: int, body: TagsBody = Body(...), db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Add tags to the video's MATCH (creates new keys/values). Body {tags:[{key,value}]} or a bare list."""
    v = _get_user_video(db, user, video_id)
    tagging.add_tags(db, user.user_id, v.match_id, tag_list(body))
    db.commit()
    return _out(db, user, _get_user_video(db, user, video_id), detail=True)  # video object incl. tags


@router.put("/{video_id}/tags", response_model=VideoDetailOut)
def replace_video_tags(video_id: int, body: TagsBody = Body(...), db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """Replace the full tag set of the video's match ([] clears it)."""
    v = _get_user_video(db, user, video_id)
    tagging.replace_tags(db, user.user_id, v.match_id, tag_list(body))
    db.commit()
    return _out(db, user, _get_user_video(db, user, video_id), detail=True)  # video object incl. tags


@router.delete("/{video_id}/tags", status_code=status.HTTP_204_NO_CONTENT)
def delete_video_tag(video_id: int, key: str = Query(...), value: Optional[str] = Query(None),
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    """Remove key=value (or all values of key) from the video's match. Idempotent 204."""
    v = _get_user_video(db, user, video_id)
    tagging.remove_tags(db, user.user_id, v.match_id, key, value)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
