"""Player tracking API ("tracks", migration 008). Public contract adopted with the frontend on 2026-10-02
(docs/API.md "Player tracking"; sync/CONTRACT_track_player.md):

  GET    /api/videos/{id}/frame?frame=N|t=s   JPEG still (Bearer or ?token= from frame_url)
  GET    /api/videos/{id}/detections?frame=N|t=s   people on that frame, boxes [x, y, w, h] normalised 0-1
  POST   /api/videos/{id}/tracks              start a track -> 202 + the full track object
  GET    /api/videos/{id}/tracks              this video's tracks, newest first
  GET    /api/tracks/{track_id}               one track (poll while queued|processing)
  GET    /api/tracks/{track_id}/frames?start=&end=   per-frame boxes (Bearer or ?token= from frames_url)
  GET    /api/tracks/{track_id}/annotated.mp4 annotated MP4, HTTP Range (Bearer or ?token= from annotated_url)
  DELETE /api/tracks/{track_id}               204

Owner only everywhere (another user's video/track = 404). Frames are 0-based at the native fps, t = f / fps.
"""
import json
import logging
import shutil
import threading
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database import get_db
from media import media_user, ranged_file_response
from models import (MatchVideo, Player, PlayerMatchStat, PlayerTrack, Team, TrackingDetection, User,
                    VideoPlayerOverride)
from routers.videos import _get_user_video, not_ready_response
from schemas import DetectionsOut, TrackCreateIn, TrackFramesOut, TrackOut, TrackTargetOut
from security import create_media_token, get_current_user, oauth2_optional
from stats import has_overrides_table
import tracking as trk

log = logging.getLogger(__name__)
router = APIRouter(tags=["tracking"])
_create_lock = threading.Lock()   # check-then-insert for "one active track per video" (single API process)
ACTIVE = ("queued", "processing")


def _require_table(db: Session) -> None:
    if not trk.has_track_table(db):
        raise HTTPException(status_code=503, detail="Player tracking needs migrations/008_player_tracks.sql")


def _frame_param(geo: trk.Geometry, t: Optional[float], frame: Optional[int]) -> int:
    if t is not None and frame is not None:
        raise HTTPException(status_code=422, detail="Give ?frame=<index> or ?t=<seconds>, not both")
    if t is None and frame is None:
        frame = 0
    try:
        return trk.resolve_frame(geo, t=t, frame=frame)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _cv_http_error(exc: trk.TrackError) -> HTTPException:
    code = {"cv_unavailable": 503, "source_missing": 409, "timeout": 504}.get(exc.code, 502)
    return HTTPException(status_code=code, detail=str(exc))


def _detections(db: Session, user_id: int, video_id: int, t: Optional[float], frame: Optional[int]):
    v = db.scalar(select(MatchVideo).where(MatchVideo.video_id == video_id, MatchVideo.user_id == user_id))
    if v is None:
        raise HTTPException(status_code=404, detail="Video not found")
    n = _frame_param(trk.geometry(v), t, frame)
    try:
        data, _cached = trk.get_detections(v, n)
    except trk.TrackError as exc:
        raise _cv_http_error(exc)
    return v, n, data


# ---------------------------------------------------------------- frame still + detections
@router.get("/api/videos/{video_id}/frame", response_class=FileResponse,
            responses={200: {"content": {"image/jpeg": {}}}, 401: {"description": "No/invalid auth"},
                       404: {"description": "Video not found"}, 422: {"description": "t/frame outside the clip"}})
def video_frame(video_id: int,
                frame: Optional[int] = Query(None, ge=0, description="0-based frame index (default 0)"),
                t: Optional[float] = Query(None, ge=0, description="Seconds into the clip (instead of frame)"),
                token: Optional[str] = Query(None, description="Media token from frame_url (for <img src>)"),
                bearer: Optional[str] = Depends(oauth2_optional), db: Session = Depends(get_db)):
    """JPEG of one frame in source-video resolution (pick-mode still, crop thumbnails). Auth: Bearer, or the
    `?token=` in `frame_url` (scoped to this video, short-lived). Cached per (video, frame) with its detections."""
    user_id = media_user(db, bearer, token, f"frame:{video_id}")
    _, n, _ = _detections(db, user_id, video_id, t, frame)
    return FileResponse(trk.frame_cache_dir(video_id, n) / "frame.jpg", media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=3600"})


@router.get("/api/videos/{video_id}/detections", response_model=DetectionsOut, response_model_by_alias=True,
            responses={404: {"description": "Video not found"}, 422: {"description": "t/frame outside the clip"},
                       502: {"description": "cv.detect_frame failed"}, 503: {"description": "CV forced real but missing"}})
def video_detections(video_id: int,
                     frame: Optional[int] = Query(None, ge=0, description="0-based frame index (default 0)"),
                     t: Optional[float] = Query(None, ge=0, description="Seconds into the clip (instead of frame)"),
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """People detected on one frame (pick mode). bbox = [x, y, w, h] normalised 0-1, top-left origin.
    player_id = the app player when the processed video's own detections match the box, else null.
    team 'A'|'B'|null; class player|goalkeeper|referee. frame_url = the matching JPEG (token in the URL)."""
    v, n, data = _detections(db, user.user_id, video_id, t, frame)
    tok = create_media_token(user.user_id, f"frame:{video_id}")
    return DetectionsOut(frame=data["frame"], t=data["t"], width=data["width"], height=data["height"],
                         frame_url=f"/api/videos/{video_id}/frame?frame={n}&token={tok}",
                         source=data["source"], players=data["players"])


# ---------------------------------------------------------------- tracks
def _loads(raw: Optional[str]):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _track_out(tr: PlayerTrack) -> TrackOut:
    meta = _loads(tr.meta) or {}
    meta = meta if isinstance(meta, dict) else {}
    done = tr.status == "done"
    cv_target = meta.get("target") or {}
    bbox = [tr.bbox_x, tr.bbox_y, tr.bbox_w, tr.bbox_h] if tr.bbox_x is not None else None
    summary = None
    if done and meta:
        summary = {k: meta.get(k) for k in ("tracked_frames", "occluded_frames", "lost_frames", "coverage_pct",
                                            "avg_conf", "reacquisition_count", "lost_segments")}
        summary.update({"player_uid": cv_target.get("player_uid"), "track_ids": cv_target.get("track_ids"),
                        "schema_version": meta.get("schema_version"), "pipeline_version": meta.get("pipeline_version"),
                        "tracker": meta.get("tracker")})
    tok = create_media_token(tr.user_id, f"track:{tr.track_id}")
    return TrackOut(
        track_id=tr.track_id, video_id=tr.video_id, status=tr.status, stage=tr.stage or "queued",
        progress=tr.progress or 0, error_message=tr.error_message,
        error_code=trk.error_code(tr.error_message) if tr.status == "failed" else None,
        target=TrackTargetOut(
            mode=tr.target_mode, player_id=tr.player_id,
            jersey_number=tr.jersey_number if tr.jersey_number is not None else cv_target.get("jersey_number"),
            team=tr.team or cv_target.get("team"), frame=tr.init_frame, t=tr.init_t, bbox=bbox),
        fps=tr.fps, frame_count=tr.frame_count, width=tr.width, height=tr.height,
        annotated_url=f"/api/tracks/{tr.track_id}/annotated.mp4?token={tok}" if done else None,
        frames_url=f"/api/tracks/{tr.track_id}/frames?token={tok}",
        source=meta.get("adapter_source") if done and meta.get("adapter_source") in ("real", "stub") else None,
        summary=summary, stats=_loads(tr.stats) if done else None,
        warnings=[str(w) for w in meta.get("warnings") or []],
        created_at=tr.created_at, updated_at=tr.updated_at or tr.created_at, finished_at=tr.finished_at)


def _get_user_track(db: Session, user_id: int, track_id: int) -> PlayerTrack:
    _require_table(db)
    tr = db.scalar(select(PlayerTrack).where(PlayerTrack.track_id == track_id, PlayerTrack.user_id == user_id))
    if tr is None:
        raise HTTPException(status_code=404, detail="Track not found")
    return tr


def _owns_player(db: Session, user: User, player_id: int) -> bool:
    return db.scalar(select(Player.player_id).join(Team, Team.team_id == Player.team_id)
                     .where(Player.player_id == player_id, Team.user_id == user.user_id)) is not None


def _resolve_player(db: Session, user: User, v: MatchVideo, geo: trk.Geometry, player_id: int,
                    frame: Optional[int]) -> tuple[Optional[int], Optional[list[float]], Optional[int]]:
    """player_id -> (init_frame, normalised bbox, jersey_number) from the processed video's stored detections
    (nearest to `frame` if given, else the first one); without detections, falls back to the shirt number."""
    p = db.scalar(select(Player).join(Team, Team.team_id == Player.team_id)
                  .where(Player.player_id == player_id, Team.user_id == user.user_id))
    if p is None:
        raise HTTPException(status_code=422, detail=f"player_id {player_id} not found")
    jersey = p.jersey_number
    if has_overrides_table(db):
        o = db.get(VideoPlayerOverride, (v.video_id, player_id))
        if o is not None and o.jersey_number is not None:
            jersey = o.jersey_number
    q = select(TrackingDetection).where(TrackingDetection.video_id == v.video_id,
                                        TrackingDetection.player_id == player_id,
                                        TrackingDetection.object_class != "ball",
                                        TrackingDetection.frame_number < geo.total_frames)
    if frame is not None:
        q = q.order_by(func.abs(TrackingDetection.frame_number - frame), TrackingDetection.frame_number)
    else:
        q = q.order_by(TrackingDetection.frame_number)
    for d in db.scalars(q.limit(200)).all():
        box = trk.clip_px(trk.norm_bbox([d.bbox_x1, d.bbox_y1, d.bbox_x2, d.bbox_y2]), geo.width, geo.height)
        if box is not None:  # skip stored boxes that don't fit this video's frame
            return d.frame_number, trk.px_to_norm(box, geo.width, geo.height), jersey
    in_video = db.scalar(select(func.count()).select_from(PlayerMatchStat).where(
        PlayerMatchStat.video_id == v.video_id, PlayerMatchStat.player_id == player_id))
    if not in_video:
        raise HTTPException(status_code=422, detail=f"player_id {player_id} does not appear in this video")
    if jersey is None:
        raise HTTPException(status_code=422, detail=f"player_id {player_id} has no stored detections and no shirt "
                                                    "number in this video; pick a box instead")
    return None, None, jersey


@router.post("/api/videos/{video_id}/tracks", response_model=TrackOut, status_code=status.HTTP_202_ACCEPTED,
             responses={404: {"description": "Video not found"},
                        409: {"description": "Video not processed yet, or a track is already active for it"},
                        422: {"description": "Bad target (body, frame/t outside the clip, unknown player_id)"},
                        503: {"description": "Migration 008 not run yet"}})
def create_track(video_id: int, background_tasks: BackgroundTasks, body: TrackCreateIn = Body(...),
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Start following one player through the clip (background; poll GET /api/tracks/{track_id}).
    Body `{frame?|t?, bbox?, player_id?, jersey_number?, team?}`: needs bbox + frame/t, OR player_id, OR
    jersey_number (team always optional). bbox = [x, y, w, h] normalised 0-1 on that frame. Returns 202 with the
    full track object. One active (queued/processing) track per video: 409 `{detail, track_id, status, progress}`."""
    v = _get_user_video(db, user, video_id)
    _require_table(db)
    if (resp := not_ready_response(v)) is not None:
        return resp
    geo = trk.geometry(v)
    tr = PlayerTrack(video_id=v.video_id, user_id=user.user_id, target_mode=body.mode, status="queued",
                     stage="queued", progress=0, player_id=body.player_id, jersey_number=body.jersey_number,
                     team=body.team, fps=geo.fps, frame_count=geo.total_frames, width=geo.width, height=geo.height)
    frame = None
    if body.frame is not None or body.t is not None:
        frame = _frame_param(geo, body.t, body.frame)
    if body.mode == "bbox":
        x, y, w, h = body.bbox
        x, y = max(0.0, x), max(0.0, y)
        w, h = min(w, 1.0 - x), min(h, 1.0 - y)
        if w * geo.width < 2 or h * geo.height < 2:
            raise HTTPException(status_code=422, detail=f"bbox must be at least 2 px wide/high in the "
                                                        f"{geo.width}x{geo.height} source video")
        tr.init_frame, tr.bbox_x, tr.bbox_y, tr.bbox_w, tr.bbox_h = frame, round(x, 4), round(y, 4), round(w, 4), round(h, 4)
    elif body.mode == "player":
        init_frame, box, jersey = _resolve_player(db, user, v, geo, body.player_id, frame)
        tr.init_frame = init_frame
        if box is not None:
            tr.bbox_x, tr.bbox_y, tr.bbox_w, tr.bbox_h = box
        if tr.jersey_number is None:
            tr.jersey_number = jersey
    else:
        tr.init_frame = None
    tr.init_t = geo.t_of(tr.init_frame) if tr.init_frame is not None else None
    if body.player_id is not None and body.mode == "bbox" and not _owns_player(db, user, body.player_id):
        tr.player_id = None  # a stale / foreign label is dropped; the box is the target
    with _create_lock:
        active = db.scalar(select(PlayerTrack).where(PlayerTrack.video_id == v.video_id,
                                                     PlayerTrack.status.in_(ACTIVE)).limit(1))
        if active is not None:
            return JSONResponse(status_code=409, content={
                "detail": "A track is already running for this video", "track_id": active.track_id,
                "status": active.status, "progress": active.progress})
        db.add(tr)
        db.commit()
    background_tasks.add_task(trk.process_track, tr.track_id)
    db.refresh(tr)
    return _track_out(tr)


@router.get("/api/videos/{video_id}/tracks", response_model=list[TrackOut],
            responses={404: {"description": "Video not found"}, 503: {"description": "Migration 008 not run yet"}})
def list_tracks(video_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """This video's tracks, newest first."""
    v = _get_user_video(db, user, video_id)
    _require_table(db)
    rows = db.scalars(select(PlayerTrack).where(PlayerTrack.video_id == v.video_id,
                                                PlayerTrack.user_id == user.user_id)
                      .order_by(PlayerTrack.track_id.desc())).all()
    return [_track_out(tr) for tr in rows]


@router.get("/api/tracks/{track_id}", response_model=TrackOut,
            responses={404: {"description": "Track not found"}, 503: {"description": "Migration 008 not run yet"}})
def get_track(track_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Status / stage / progress (poll every 1-2 s while queued|processing). When done: annotated_url, summary,
    stats, source. frames_url / annotated_url carry fresh short-lived tokens on every fetch."""
    return _track_out(_get_user_track(db, user.user_id, track_id))


@router.delete("/api/tracks/{track_id}", status_code=status.HTTP_204_NO_CONTENT,
               responses={404: {"description": "Track not found"}})
def delete_track(track_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    """Deletes the track and its files (track_<track_id>/). Allowed while running: the worker notices and stops."""
    tr = _get_user_track(db, user.user_id, track_id)
    out = trk.absolute(tr.output_dir) or trk.job_dir(track_id)
    db.delete(tr)
    db.commit()
    for d in {out, trk.job_dir(track_id)}:
        shutil.rmtree(d, ignore_errors=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _not_done(tr: PlayerTrack) -> Optional[JSONResponse]:
    if tr.status == "done":
        return None
    return JSONResponse(status_code=409, content={
        "detail": "Tracking failed" if tr.status == "failed" else "Tracking not finished yet",
        "status": tr.status, "stage": tr.stage, "progress": tr.progress,
        "error_message": tr.error_message if tr.status == "failed" else None,
        "error_code": trk.error_code(tr.error_message) if tr.status == "failed" else None})


def _media_track(db: Session, bearer: Optional[str], token: Optional[str], track_id: int) -> PlayerTrack:
    user_id = media_user(db, bearer, token, f"track:{track_id}")
    return _get_user_track(db, user_id, track_id)


@router.get("/api/tracks/{track_id}/frames", response_model=TrackFramesOut,
            responses={401: {"description": "No/invalid auth"}, 404: {"description": "Track not found"},
                       409: {"description": "Not done yet / failed"}, 422: {"description": "start > end"}})
def get_track_frames(track_id: int,
                     start: Optional[int] = Query(None, ge=0, description="First frame (inclusive, default 0)"),
                     end: Optional[int] = Query(None, ge=0, description="Last frame (inclusive, default last)"),
                     token: Optional[str] = Query(None, description="Media token from frames_url"),
                     bearer: Optional[str] = Depends(oauth2_optional), db: Session = Depends(get_db)):
    """Per-frame boxes of the tracked player: `{track_id, source, fps, width, height, frame_count, start, end,
    frames:[{f, t, bbox [x,y,w,h] 0-1 | null, conf, state tracked|occluded|lost, pitch_x, pitch_y}]}`. Dense:
    one entry per frame in [start, end]. `occluded` = interpolated estimate; `lost` = bbox null, conf 0.
    Auth: Bearer, or the `?token=` in frames_url."""
    tr = _media_track(db, bearer, token, track_id)
    if (resp := _not_done(tr)) is not None:
        return resp
    p = trk.absolute(tr.frames_path)
    if p is None or not p.is_file():
        raise HTTPException(status_code=404, detail="Track data missing on the server")
    doc = json.loads(p.read_text())
    total = int(doc.get("frame_count") or len(doc.get("frames") or []))
    a = 0 if start is None else start
    b = max(0, total - 1) if end is None else min(end, max(0, total - 1))
    if a > b and not (start is None and end is None):
        raise HTTPException(status_code=422, detail=f"start must be <= end (frames 0..{total - 1})")
    frames = [f for f in doc.get("frames") or [] if a <= f["f"] <= b]
    return TrackFramesOut(track_id=track_id, source=doc.get("source") or "real", fps=doc["fps"], width=doc["width"],
                          height=doc["height"], frame_count=total, start=a, end=b, frames=frames)


@router.head("/api/tracks/{track_id}/annotated.mp4", include_in_schema=False)
@router.get("/api/tracks/{track_id}/annotated.mp4", response_class=Response,
            responses={200: {"content": {"video/mp4": {}}}, 206: {"description": "Partial content (Range)"},
                       401: {"description": "No/invalid/expired auth"}, 404: {"description": "Track not found"},
                       409: {"description": "Not done yet"}, 416: {"description": "Range not satisfiable"}})
def annotated_mp4(track_id: int, request: Request,
                  token: Optional[str] = Query(None, description="Media token from annotated_url (for <video src>)"),
                  bearer: Optional[str] = Depends(oauth2_optional), db: Session = Depends(get_db)):
    """Annotated video (H.264 yuv420p, faststart; same fps and frame count as the source). Auth: Bearer, or the
    `?token=` in annotated_url (scoped to this track, short-lived; re-fetch the track for a fresh URL).
    Full HTTP Range support for seeking."""
    tr = _media_track(db, bearer, token, track_id)
    if (resp := _not_done(tr)) is not None:
        return resp
    p = trk.absolute(tr.annotated_path)
    if p is None or not p.is_file():
        raise HTTPException(status_code=404, detail="Annotated video missing on the server")
    return ranged_file_response(request, p, "video/mp4")
