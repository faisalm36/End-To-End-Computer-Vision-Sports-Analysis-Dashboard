"""Player tracking ("tracks", migration 008): frame stills + detections for pick mode, and background
"follow one player" tracks with a per-frame box list and an annotated MP4.

PUBLIC contract (docs/API.md, sync/CONTRACT_track_player.md; adopted with the frontend 2026-10-02): every box is
NORMALISED [x, y, w, h] (0-1, top-left origin); frames are 0-based at the native fps, t = f / fps; per-frame
state is tracked | occluded (interpolated bbox) | lost (bbox null). The conversion from the CV's pixel output
happens HERE (read_track_output, detections) so the CV interface below stays pixel-based.

CV interface (proposed by the backend, confirmed by the CV engineer 2026-10-02). The two command builders below are
the ONLY place that knows the flags; change them there if the interface changes.
  (A) python -m cv.detect_frame --video <abs> --t <sec> --out <dir> --device <d> [--model m]
      -> <dir>/frame.jpg, <dir>/candidates.json
         {frame, t, width, height, candidates: [{bbox:[x1,y1,x2,y2], confidence, team:'A'|'B'|null,
                                                 jersey_number|null, class}]}
  (B) python -m cv.track_player --video <abs> --out <dir> --device <d>
          (--frame N --bbox x1,y1,x2,y2 | --jersey N [--team A|B]) [--model m] [--calibration p]
      prints 'Processing frames: N%' (flushed) and writes
      -> <dir>/track.json {schema_version?, fps, width, height, total_frames,
                           target: {jersey_number, team, init_frame, player_uid?, track_ids?},
                           frames: [{frame, t, bbox|null, confidence|null, status: tracked|interpolated|lost,
                                     state?: tracked|occluded|lost|reacquired, pitch_x?, pitch_y?}]}
         <dir>/replay.mp4 (same fps + frame count as the source), <dir>/meta.json {pipeline_version, tracker,
                           coverage_pct, lost_frames, warnings, reacquisition_count?, lost_segments?}
         <dir>/target_stats.json (optional; shaped like a player_match_stats row)
      exit code 3 = target_not_found.
  Both run with cwd = repo root and PYTHONPATH = repo root (same as cv.run_pipeline). Teams are 'A'/'B'.
  CV coordinates are SOURCE VIDEO PIXELS (x right, y down, origin top-left).

Per-frame normalisation (read_track_output): a CV `state` wins when present (reacquired -> tracked, occluded ->
occluded if it has a bbox else lost, lost -> bbox null); otherwise `status` maps tracked -> tracked,
interpolated -> occluded, lost -> lost. A frame without a bbox is always 'lost' (conf 0). Missing frames are
filled in as lost, so `frames` is dense (0 .. frame_count-1).

Modes: settings.TRACK_PIPELINE_MODE, independent of CV_PIPELINE_MODE. auto (default) = real only if BOTH
cv/track_player.py and cv/detect_frame.py exist under the CV repo root (pipeline.repo_root()), else the stub; so a
checkout without the tracking modules runs the stub and switches to real automatically once they land.
real = always the CV modules (fails clearly if missing), stub = always fake. The STUB uses the video's stored
detections for the requested frame when there are any (so player_id is real), else 10-14 fake boxes; it fakes a
smooth track from the chosen box with occluded/lost gaps, and renders a real annotated MP4 with ffmpeg
(H.264 yuv420p +faststart, same fps and frame count as the source). Stub output is marked source='stub' and
carries a warning.
"""
from __future__ import annotations

import json
import logging
import math
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import inspect, select

from config import BASE_DIR, settings
from database import SessionLocal
from models import MatchVideo, PlayerTrack
from timeutil import utcnow

log = logging.getLogger("tracking")

EXIT_TARGET_NOT_FOUND = 3
ERROR_CODES = ("target_not_found", "cv_unavailable", "cv_failed", "timeout", "interrupted", "source_missing",
               "bad_output")
FRAMES_API_FILE = "frames_api.json"    # public per-frame track the API serves (raw CV files are kept next to it)
_TQDM = re.compile(r"Processing frames:\s+(\d{1,3})%")


class TrackError(RuntimeError):
    """A failure with a stable machine code (prefix of error_message, e.g. 'target_not_found: ...')."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


class JobDeleted(Exception):
    """The player_tracks row (or its video) was deleted while we were working on it."""


def error_code(message: Optional[str]) -> Optional[str]:
    if not message:
        return None
    head = message.split(":", 1)[0].strip()
    return head if head in ERROR_CODES else "cv_failed"


# --------------------------------------------------------------------------- table presence (deploy order)
_table_ok = False


def has_track_table(db) -> bool:
    """True once migration 008 exists (cached once found), so new code before the migration only 503s here."""
    global _table_ok
    if not _table_ok:
        _table_ok = inspect(db.get_bind()).has_table(PlayerTrack.__tablename__)
    return _table_ok


# --------------------------------------------------------------------------- paths / geometry
def output_root() -> Path:
    return Path(settings.CV_OUTPUT_DIR)


def job_dir(track_id: int) -> Path:
    return output_root() / f"track_{track_id}"


def frames_dir(video_id: int) -> Path:
    return output_root() / "frames" / f"video_{video_id}"


def frame_cache_dir(video_id: int, frame: int) -> Path:
    return frames_dir(video_id) / f"frame_{frame:07d}"


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(BASE_DIR))
    except ValueError:
        return str(path.resolve())


def absolute(path_str: Optional[str]) -> Optional[Path]:
    if not path_str:
        return None
    p = Path(path_str)
    return p if p.is_absolute() else BASE_DIR / p


def video_file(video: MatchVideo) -> Path:
    return absolute(video.file_path)


@dataclass(frozen=True)
class Geometry:
    width: int
    height: int
    fps: float
    duration: float
    total_frames: int
    readable: bool  # False = couldn't probe the file (fake/missing); values come from pipeline_meta / defaults

    def t_of(self, frame: int) -> float:
        return round(frame / self.fps, 3)


_geo_cache: dict[tuple, Geometry] = {}


def _f(v) -> Optional[float]:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _i(v) -> Optional[int]:
    if isinstance(v, bool):
        return None
    x = _f(v)
    return int(x) if x is not None and float(x).is_integer() else None


def _probe(path: Path) -> Optional[tuple[int, int, float, float, Optional[int]]]:
    exe = shutil.which("ffprobe")
    if not exe or not path.is_file():
        return None
    try:
        r = subprocess.run([exe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames,duration:format=duration",
                            "-of", "json", str(path)], capture_output=True, text=True, timeout=30, check=False)
        data = json.loads(r.stdout or "{}")
        st = (data.get("streams") or [{}])[0]
        w, h = _i(st.get("width")), _i(st.get("height"))
        dur = _f(st.get("duration")) or _f((data.get("format") or {}).get("duration"))
        fps = None
        for k in ("avg_frame_rate", "r_frame_rate"):
            num, _, den = str(st.get(k) or "").partition("/")
            if _f(num) and _f(den or "1"):
                fps = _f(num) / _f(den or "1")
                break
        if w and h and dur and dur > 0 and fps and 0 < fps <= 240:
            return w, h, fps, dur, _i(st.get("nb_frames"))
    except (OSError, subprocess.SubprocessError, ValueError, IndexError, AttributeError):
        pass
    return None


def geometry(video: MatchVideo) -> Geometry:
    """Width/height/fps/duration of the uploaded file (ffprobe), else from pipeline_meta, else 1920x1080 @ fps 30, 1 s."""
    path = video_file(video)
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        key = None
    if key and key in _geo_cache:
        return _geo_cache[key]
    probed = _probe(path) if path else None
    if probed:
        w, h, fps, dur, nb = probed
        total = nb if nb and nb > 0 else max(1, int(round(dur * fps)))
        geo = Geometry(w, h, round(fps, 3), round(dur, 3), total, True)
        if key:
            _geo_cache[key] = geo
        return geo
    try:
        meta = json.loads(video.pipeline_meta or "{}")
        meta = meta if isinstance(meta, dict) else {}
    except ValueError:
        meta = {}
    res = meta.get("resolution")
    w = h = None
    if isinstance(res, (list, tuple)) and len(res) == 2:
        w, h = _i(res[0]), _i(res[1])
    elif isinstance(res, str) and "x" in res:
        a, _, b = res.partition("x")
        w, h = _i(a), _i(b)
    w, h = w or _i(meta.get("width")) or 1920, h or _i(meta.get("height")) or 1080
    fps = _f(meta.get("fps")) or _f(video.fps) or 30.0
    dur = _f(meta.get("duration_s")) or 1.0
    total = _i(meta.get("frame_count")) or max(1, int(round(dur * fps)))
    return Geometry(w, h, round(fps, 3), round(dur, 3), total, False)


def resolve_frame(geo: Geometry, t: Optional[float] = None, frame: Optional[int] = None) -> int:
    """Frame index for ?t= (seconds) or ?frame=. ValueError (-> 422) when outside the clip."""
    if frame is None:
        if t is None or t < 0 or t > geo.duration + 1.0 / geo.fps:
            raise ValueError(f"t must be between 0 and {geo.duration:g} s (clip length)")
        frame = int(round(t * geo.fps))
    if frame < 0 or frame >= geo.total_frames + 1:
        raise ValueError(f"frame must be between 0 and {geo.total_frames - 1}")
    return min(frame, geo.total_frames - 1)


# --------------------------------------------------------------------------- mode + CV command builders
def _cv_root() -> Path:
    from pipeline import repo_root
    return repo_root()


def track_mode(module: str) -> str:
    """'real' | 'stub' for cv.<module> (detect_frame or track_player); both modules decide together in auto."""
    mode = (settings.TRACK_PIPELINE_MODE or "auto").strip().lower()
    if mode in ("real", "stub"):
        return mode
    cv = _cv_root() / "cv"
    return "real" if all((cv / f"{m}.py").is_file() for m in TRACK_MODULES) else "stub"


TRACK_MODULES = ("detect_frame", "track_player")


def _num(v: float) -> str:
    return f"{round(float(v), 2):g}"


def build_detect_frame_cmd(video_path: Path, t: float, out_dir: Path) -> list[str]:
    cmd = [settings.CV_PYTHON or sys.executable, "-m", "cv.detect_frame",
           "--video", str(video_path.resolve()), "--t", f"{t:.3f}", "--out", str(out_dir.resolve()),
           "--device", settings.CV_DEVICE]
    if settings.CV_MODEL:
        cmd += ["--model", settings.CV_MODEL]
    return cmd


@dataclass(frozen=True)
class Target:
    """What the CV gets. 'bbox' = pixel box [x1,y1,x2,y2] on `frame`; 'jersey' = shirt number (team optional).
    A 'player' track (app player_id) was resolved to one of these when it was created."""
    mode: str                        # bbox | jersey
    frame: Optional[int] = None
    bbox: Optional[tuple[float, float, float, float]] = None
    jersey_number: Optional[int] = None
    team: Optional[str] = None       # A | B | None

    @classmethod
    def of(cls, tr: PlayerTrack, geo: "Geometry") -> "Target":
        if tr.init_frame is not None and tr.bbox_x is not None:
            W, H = tr.width or geo.width, tr.height or geo.height
            return cls("bbox", tr.init_frame, tuple(norm_to_px([tr.bbox_x, tr.bbox_y, tr.bbox_w, tr.bbox_h], W, H)),
                       jersey_number=tr.jersey_number, team=tr.team)
        return cls("jersey", jersey_number=tr.jersey_number, team=tr.team)


def build_track_player_cmd(video_path: Path, out_dir: Path, target: Target) -> list[str]:
    cmd = [settings.CV_PYTHON or sys.executable, "-m", "cv.track_player",
           "--video", str(video_path.resolve()), "--out", str(out_dir.resolve()), "--device", settings.CV_DEVICE]
    if target.mode == "bbox":
        cmd += ["--frame", str(int(target.frame)), "--bbox", ",".join(_num(v) for v in target.bbox)]
    else:
        cmd += ["--jersey", str(int(target.jersey_number))]
        if target.team:
            cmd += ["--team", str(target.team)]
    if settings.CV_MODEL:
        cmd += ["--model", settings.CV_MODEL]
    if settings.CV_CALIBRATION_PATH:
        cmd += ["--calibration", str(Path(settings.CV_CALIBRATION_PATH).expanduser().resolve())]
    return cmd


def _cv_env() -> dict:
    env = os.environ.copy()
    root = str(_cv_root())
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [root, env.get("PYTHONPATH", "")]))
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def _require_module(module: str) -> None:
    path = _cv_root() / "cv" / f"{module}.py"
    if not path.is_file():
        raise TrackError("cv_unavailable", f"CV module not found at {path} (the CV checkout has no cv.{module} yet). "
                                           "Set TRACK_PIPELINE_MODE=auto or stub for demo data.")


def _log_tail(path: Path, lines: int = 15) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").replace("\r", "\n").splitlines()[-lines:])
    except OSError:
        return ""


# --------------------------------------------------------------------------- small normalisers
def norm_team(v) -> Optional[str]:
    if isinstance(v, str) and v.strip().upper() in ("A", "B"):
        return v.strip().upper()
    i = _i(v)
    return {0: "A", 1: "B"}.get(i) if i is not None else None


def norm_jersey(v) -> Optional[int]:
    i = _i(v)
    if i is None and isinstance(v, str) and v.strip().isdigit():
        i = int(v.strip())
    return i if i is not None and 0 <= i <= 99 else None


def norm_bbox(v, d: Optional[dict] = None) -> Optional[list[float]]:
    if v is None and d is not None and all(k in d for k in ("bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2")):
        v = [d["bbox_x1"], d["bbox_y1"], d["bbox_x2"], d["bbox_y2"]]
    if not isinstance(v, (list, tuple)) or len(v) != 4:
        return None
    xs = [_f(x) for x in v]
    if any(x is None for x in xs) or xs[2] <= xs[0] or xs[3] <= xs[1]:
        return None
    return [round(x, 1) for x in xs]


def _conf(v) -> Optional[float]:
    c = _f(v)
    return round(min(max(c, 0.0), 1.0), 3) if c is not None else None

def px_to_norm(b, W: int, H: int) -> list[float]:
    """[x1, y1, x2, y2] pixels -> normalised [x, y, w, h] (0-1, clipped to the frame)."""
    x1, y1 = min(max(b[0], 0.0), W), min(max(b[1], 0.0), H)
    x2, y2 = min(max(b[2], 0.0), W), min(max(b[3], 0.0), H)
    return [round(x1 / W, 4), round(y1 / H, 4), round(max(0.0, x2 - x1) / W, 4), round(max(0.0, y2 - y1) / H, 4)]



def enrich_detection_pixels(players: list[dict], W: int, H: int) -> None:
    """Add bbox_xyxy + ERD centre/size (pixels) from normalised bbox [x,y,w,h]. Mutates in place."""
    for p in players:
        b = p.get("bbox")
        if not (isinstance(b, (list, tuple)) and len(b) == 4 and W > 0 and H > 0):
            continue
        x, y, w, h = b
        x1, y1, x2, y2 = x * W, y * H, (x + w) * W, (y + h) * H
        p["bbox_xyxy"] = [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)]
        p["x_center"] = round((x1 + x2) / 2.0, 2)
        p["y_center"] = round((y1 + y2) / 2.0, 2)
        p["bbox_width"] = round(abs(x2 - x1), 2)
        p["bbox_height"] = round(abs(y2 - y1), 2)


def norm_to_px(b, W: int, H: int) -> list[float]:
    """normalised [x, y, w, h] -> [x1, y1, x2, y2] pixels."""
    x, y, w, h = (float(v) for v in b)
    return [round(x * W, 1), round(y * H, 1), round((x + w) * W, 1), round((y + h) * H, 1)]


def clip_px(b, W: int, H: int, min_px: float = 2.0) -> Optional[list[float]]:
    """Pixel box clipped to the W x H frame; None if less than min_px wide/high is left (e.g. stored detections in
    another resolution)."""
    if b is None:
        return None
    x1, y1, x2, y2 = max(0.0, b[0]), max(0.0, b[1]), min(float(W), b[2]), min(float(H), b[3])
    return [x1, y1, x2, y2] if x2 - x1 >= min_px and y2 - y1 >= min_px else None


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0



# --------------------------------------------------------------------------- ffmpeg helpers
_encoder: Optional[list[str]] = None


def _h264_args() -> list[str]:
    global _encoder
    if _encoder is None:
        exe = shutil.which("ffmpeg")
        names = ""
        if exe:
            try:
                names = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True,
                                       timeout=30).stdout
            except (OSError, subprocess.SubprocessError):
                names = ""
        if re.search(r"\blibx264\b", names):
            _encoder = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]
        elif re.search(r"\bh264_videotoolbox\b", names):
            _encoder = ["-c:v", "h264_videotoolbox", "-b:v", "5M"]
        elif re.search(r"\blibopenh264\b", names):
            _encoder = ["-c:v", "libopenh264", "-b:v", "5M"]
        else:
            _encoder = []
    if not _encoder:
        raise TrackError("cv_unavailable", "ffmpeg with an H.264 encoder (libx264) is needed for the stub replay")
    return list(_encoder)


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise TrackError("cv_unavailable", "ffmpeg not found on PATH (needed by the tracking stub)")
    return exe


def _extract_frame(src: Path, t: float, dest: Path) -> bool:
    try:
        r = subprocess.run([_ffmpeg(), "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1",
                            "-q:v", "3", str(dest)], capture_output=True, timeout=60)
        if r.returncode == 0 and dest.is_file() and dest.stat().st_size > 0:
            return True
        if t > 0:  # seeking past the last decodable frame: take the last one
            r = subprocess.run([_ffmpeg(), "-v", "error", "-y", "-sseof", "-0.5", "-i", str(src), "-update", "1",
                                "-q:v", "3", str(dest)], capture_output=True, timeout=60)
            return r.returncode == 0 and dest.is_file() and dest.stat().st_size > 0
    except (OSError, subprocess.SubprocessError):
        pass
    return False


PITCH_GREEN = "0x2e7d32"


def _synthetic_frame(geo: Geometry, boxes: list[list[float]], dest: Path) -> None:
    """Unreadable source (stub only): a green canvas with the candidate boxes filled in."""
    draws = "".join(f",drawbox=x={b[0]:.0f}:y={b[1]:.0f}:w={b[2] - b[0]:.0f}:h={b[3] - b[1]:.0f}:color=white@0.8:t=fill"
                    for b in boxes)
    r = subprocess.run([_ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"color=c={PITCH_GREEN}:s={geo.width}x{geo.height}:d=1", "-vf", "null" + draws,
                        "-frames:v", "1", "-q:v", "3", str(dest)], capture_output=True, timeout=60)
    if r.returncode != 0 or not dest.is_file():
        raise TrackError("cv_failed", f"ffmpeg could not draw the stub frame: {r.stderr.decode(errors='replace')[-300:]}")


# --------------------------------------------------------------------------- detections (pick mode)
DETECTIONS_FILE = "detections_api.json"
_locks: dict[tuple[int, int], threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()


def _lock_for(video_id: int, frame: int) -> threading.Lock:
    with _locks_guard:
        return _locks[(video_id, frame)]


def get_detections(video: MatchVideo, frame: int) -> tuple[dict, bool]:
    """(detections dict, cached?) for one frame; frame.jpg sits next to detections_api.json in frame_cache_dir.
    Computed once per (video, frame); concurrent requests for the same frame wait for the first one.
    Dict: {frame, t, width, height, source, players:[{player_id, jersey_number, team, class, bbox [x,y,w,h] 0-1,
    conf}]}."""
    d = frame_cache_dir(video.video_id, frame)
    cached = _load_cached(d)
    if cached is not None:
        return cached, True
    with _lock_for(video.video_id, frame):
        cached = _load_cached(d)
        if cached is not None:
            return cached, True
        geo = geometry(video)
        mode = track_mode("detect_frame")
        tmp = d.parent / f".tmp-{d.name}-{uuid.uuid4().hex[:8]}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            if mode == "stub":
                _stub_detect(video, geo, frame, tmp)
            else:
                _run_detect(video, geo, frame, tmp)
            data = _normalize_candidates(tmp, geo, frame, mode)
            _attach_player_ids(video, data)
            for p in data["players"]:
                p["bbox"] = px_to_norm(p["bbox"], data["width"], data["height"])
            enrich_detection_pixels(data["players"], data["width"], data["height"])
            (tmp / DETECTIONS_FILE).write_text(json.dumps(data))
            shutil.rmtree(d, ignore_errors=True)
            os.replace(tmp, d)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return data, False


def _load_cached(d: Path) -> Optional[dict]:
    p = d / DETECTIONS_FILE
    if p.is_file() and (d / "frame.jpg").is_file():
        try:
            data = json.loads(p.read_text())
            if isinstance(data, dict) and data.get("players"):
                # Older cache entries lack pixel ERD fields; derive them on read.
                if any("x_center" not in pl for pl in data["players"] if isinstance(pl, dict)):
                    enrich_detection_pixels(data["players"], int(data.get("width") or 0), int(data.get("height") or 0))
            return data
        except ValueError:
            return None
    return None


def _run_detect(video: MatchVideo, geo: Geometry, frame: int, out_dir: Path) -> None:
    _require_module("detect_frame")
    src = video_file(video)
    if not src or not src.is_file():
        raise TrackError("source_missing", "the uploaded video file is missing on the server")
    cmd = build_detect_frame_cmd(src, geo.t_of(frame), out_dir)
    log_path = out_dir / "detect.log"
    with log_path.open("w") as lf:
        lf.write("$ " + shlex.join(cmd) + "\n")
        lf.flush()
        try:
            proc = subprocess.run(cmd, cwd=_cv_root(), env=_cv_env(), stdout=lf, stderr=subprocess.STDOUT,
                                  timeout=settings.CV_DETECT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            raise TrackError("timeout", f"cv.detect_frame took longer than {settings.CV_DETECT_TIMEOUT_SECONDS}s")
        except OSError as exc:
            raise TrackError("cv_unavailable", f"could not start cv.detect_frame ({cmd[0]}): {exc}")
    if proc.returncode != 0:
        raise TrackError("cv_failed", f"cv.detect_frame exited with code {proc.returncode}. Log tail:\n"
                                      f"{_log_tail(log_path)}")


CLASSES = ("player", "goalkeeper", "referee")


def _norm_class(v) -> str:
    s = str(v or "player").strip().lower()
    return s if s in CLASSES else ("goalkeeper" if s in ("gk", "keeper") else "player")


def _normalize_candidates(out_dir: Path, geo: Geometry, frame: int, source: str) -> dict:
    """candidates.json (pixels) -> {frame, t, width, height, source, players:[... bbox still in PIXELS]}."""
    if not (out_dir / "frame.jpg").is_file():
        raise TrackError("bad_output", "cv.detect_frame wrote no frame.jpg")
    try:
        raw = json.loads((out_dir / "candidates.json").read_text())
    except FileNotFoundError:
        raise TrackError("bad_output", "cv.detect_frame wrote no candidates.json")
    except ValueError as exc:
        raise TrackError("bad_output", f"candidates.json is not valid JSON: {exc}")
    raw = raw if isinstance(raw, dict) else {"candidates": raw if isinstance(raw, list) else []}
    width, height = _i(raw.get("width")) or geo.width, _i(raw.get("height")) or geo.height
    out = []
    for c in raw.get("candidates") or raw.get("players") or []:
        if not isinstance(c, dict):
            continue
        bbox = norm_bbox(c.get("bbox"), c)
        if bbox is None:
            continue
        cls = _norm_class(c.get("class"))
        pid = _i(c.get("player_id"))  # only set by the stub (stored detections); CV ids are matched below
        out.append({"player_id": pid if pid and pid > 0 else None, "jersey_number": norm_jersey(c.get("jersey_number")),
                    "team": None if cls == "referee" else norm_team(c.get("team")), "class": cls, "bbox": bbox,
                    "conf": _conf(c.get("confidence", c.get("conf"))) or 0.0})
    f = _i(raw.get("frame"))
    f = f if f is not None and f >= 0 else frame
    t = _f(raw.get("t"))
    return {"frame": f, "t": round(t, 3) if t is not None else geo.t_of(f), "width": width, "height": height,
            "source": source, "players": out}


def _stored_detections(video_id: int, frame: int) -> list:
    """The processed video's own detections (tracking_detections) on exactly this frame, people only."""
    from models import Player, TrackingDetection
    db = SessionLocal()
    try:
        rows = db.execute(select(TrackingDetection, Player.jersey_number)
                          .outerjoin(Player, Player.player_id == TrackingDetection.player_id)
                          .where(TrackingDetection.video_id == video_id, TrackingDetection.frame_number == frame,
                                 TrackingDetection.object_class != "ball")).all()
        return [(r[0].player_id, r[0].jersey_number if r[0].jersey_number is not None else r[1],
                 [r[0].bbox_x1, r[0].bbox_y1, r[0].bbox_x2, r[0].bbox_y2], r[0].confidence, r[0].object_class)
                for r in rows]
    finally:
        db.close()


def _attach_player_ids(video: MatchVideo, data: dict) -> None:
    """player_id = the app player whose stored detection on this frame overlaps the box (IoU >= 0.5), else null."""
    stored = [s for s in _stored_detections(video.video_id, data["frame"]) if s[0] is not None]
    for p in data["players"]:
        if p["player_id"] is not None or not stored:
            continue
        best = max(stored, key=lambda s: iou(p["bbox"], s[2]))
        if iou(p["bbox"], best[2]) >= 0.5:
            p["player_id"] = best[0]
            if p["jersey_number"] is None:
                p["jersey_number"] = norm_jersey(best[1])


def _stub_roster(video: MatchVideo) -> list[int]:
    from models import Match, Player
    db = SessionLocal()
    try:
        m = db.get(Match, video.match_id)
        if m is None:
            return []
        return sorted({p.jersey_number for p in db.scalars(select(Player).where(
            Player.team_id.in_([m.home_team_id, m.away_team_id]))).all() if p.jersey_number is not None})
    finally:
        db.close()


def _stub_detect(video: MatchVideo, geo: Geometry, frame: int, out_dir: Path) -> None:
    """STUB: the video's stored detections on this frame if any (real player_id), else 10-14 person-sized boxes
    (deterministic per video+frame); drawn on the real frame (ffmpeg) or a green canvas."""
    rng = random.Random(video.video_id * 1_000_003 + frame)
    W, H = geo.width, geo.height
    cands = []
    for pid, jersey, box, conf, cls in _stored_detections(video.video_id, frame):
        b = clip_px(norm_bbox(box), W, H)
        if b is not None:
            cands.append({"player_id": pid, "bbox": b, "confidence": conf, "team": None, "jersey_number": jersey,
                          "class": cls})
    if not cands:
        roster = _stub_roster(video) or list(range(1, 24))
        for i in range(rng.randint(10, 14)):
            h = H * rng.uniform(0.08, 0.16)
            w = h * rng.uniform(0.35, 0.5)
            x1 = rng.uniform(0, max(1.0, W - w))
            y1 = rng.uniform(H * 0.2, max(H * 0.2 + 1, H - h))
            cls = "referee" if i == 0 else ("goalkeeper" if i == 1 else "player")
            team = None if cls == "referee" else ("A" if i % 2 else "B")
            jersey = rng.choice(roster) if cls != "referee" and rng.random() < 0.6 else None
            cands.append({"bbox": [round(x1, 1), round(y1, 1), round(min(W, x1 + w), 1), round(min(H, y1 + h), 1)],
                          "confidence": round(rng.uniform(0.45, 0.97), 3), "team": team, "jersey_number": jersey,
                          "class": cls})
    src = video_file(video)
    if not (src and _extract_frame(src, geo.t_of(frame), out_dir / "frame.jpg")):
        _synthetic_frame(geo, [c["bbox"] for c in cands], out_dir / "frame.jpg")
    (out_dir / "candidates.json").write_text(json.dumps(
        {"frame": frame, "t": geo.t_of(frame), "width": W, "height": H, "candidates": cands}, indent=1))
    (out_dir / "STUB_OUTPUT_FAKE_DATA.txt").write_text("Generated by backend/tracking.py STUB, not by the CV model.\n")


# --------------------------------------------------------------------------- track progress
def set_track_progress(track_id: int, stage: str, progress: int) -> bool:
    """Persist stage/progress (never backwards). False if the track row is gone."""
    db = SessionLocal()
    try:
        tr = db.get(PlayerTrack, track_id)
        if tr is None:
            return False
        progress = max(0, min(100, int(progress)))
        if progress >= (tr.progress or 0) or stage in ("done", "failed"):
            tr.stage, tr.progress = stage, progress
            db.commit()
        return True
    finally:
        db.close()


# --------------------------------------------------------------------------- track entry point
def process_track(track_id: int) -> None:
    """BackgroundTask: queued -> processing (stages detect, tracking, rendering) -> done | failed. Never raises;
    tolerates the track (or its video) being deleted mid-run."""
    db = SessionLocal()
    out_dir = job_dir(track_id)
    try:
        tr = db.get(PlayerTrack, track_id)
        if tr is None:
            return
        video = db.get(MatchVideo, tr.video_id)
        if video is None:
            return
        tr.status, tr.stage, tr.progress, tr.error_message = "processing", "detect", 5, None
        tr.output_dir = rel(out_dir)
        db.commit()
        started = time.monotonic()
        try:
            shutil.rmtree(out_dir, ignore_errors=True)
            out_dir.mkdir(parents=True, exist_ok=True)
            geo = geometry(video)
            target = Target.of(tr, geo)
            mode = track_mode("track_player")
            progress = lambda stage, pct: _progress_or_raise(track_id, stage, pct)  # noqa: E731
            if mode == "stub":
                _stub_track(video, geo, target, out_dir, progress)
            else:
                _run_track_real(video, target, out_dir, progress)
            if not set_track_progress(track_id, "rendering", 96):
                raise JobDeleted()
            api, meta, stats = read_track_output(out_dir, geo, track_id, video.video_id, mode)
            meta["adapter_runtime_s"] = round(time.monotonic() - started, 2)
            (out_dir / FRAMES_API_FILE).write_text(json.dumps(api, separators=(",", ":")))
            db.expire_all()
            tr = db.get(PlayerTrack, track_id)
            if tr is None:
                raise JobDeleted()
            tr.frames_path = rel(out_dir / FRAMES_API_FILE)
            tr.annotated_path = rel(out_dir / "replay.mp4")
            tr.fps, tr.frame_count, tr.width, tr.height = api["fps"], api["frame_count"], api["width"], api["height"]
            tr.meta = json.dumps(meta, default=str)
            tr.stats = json.dumps(stats, default=str) if stats is not None else None
            tr.status, tr.stage, tr.progress, tr.error_message = "done", "done", 100, None
            tr.finished_at = utcnow()
            db.commit()
            log.info("track %s done (%s): coverage %s%%", track_id, mode, meta.get("coverage_pct"))
        except JobDeleted:
            db.rollback()
            log.info("track %s was deleted while running; stopping", track_id)
            shutil.rmtree(out_dir, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            db.expire_all()
            tr = db.get(PlayerTrack, track_id)
            if tr is None:
                shutil.rmtree(out_dir, ignore_errors=True)
                return
            if not isinstance(exc, TrackError):
                log.exception("track %s failed", track_id)
                exc = TrackError("cv_failed", f"{type(exc).__name__}: {exc}")
            else:
                log.warning("track %s failed: %s", track_id, exc)
            tr.status, tr.stage = "failed", "failed"
            tr.error_message = str(exc)[:4000]
            tr.finished_at = utcnow()
            db.commit()
    finally:
        db.close()


def _progress_or_raise(track_id: int, stage: str, pct: int) -> None:
    if not set_track_progress(track_id, stage, pct):
        raise JobDeleted()


def fail_interrupted_tracks() -> int:
    """On startup: BackgroundTasks don't survive restarts. No-op before migration 008."""
    db = SessionLocal()
    try:
        if not has_track_table(db):
            return 0
        rows = db.scalars(select(PlayerTrack).where(PlayerTrack.status.in_(["queued", "processing"]))).all()
        for tr in rows:
            tr.status, tr.stage = "failed", "failed"
            tr.error_message = "interrupted: the server restarted before tracking finished. Start it again."
            tr.finished_at = utcnow()
        db.commit()
        return len(rows)
    finally:
        db.close()


# --------------------------------------------------------------------------- real mode
def _run_track_real(video: MatchVideo, target: Target, out_dir: Path, progress: Callable[[str, int], None]) -> None:
    _require_module("track_player")
    src = video_file(video)
    if not src or not src.is_file():
        raise TrackError("source_missing", "the uploaded video file is missing on the server")
    cmd = build_track_player_cmd(src, out_dir, target)
    log_path = out_dir / "track.log"
    log.info("running cv.track_player (cwd=%s): %s", _cv_root(), shlex.join(cmd))
    deadline = time.monotonic() + settings.CV_TRACK_TIMEOUT_SECONDS
    with log_path.open("w") as lf:
        lf.write(f"# cwd={_cv_root()}\n$ " + shlex.join(cmd) + "\n")
        lf.flush()
        try:
            proc = subprocess.Popen(cmd, cwd=_cv_root(), env=_cv_env(), stdout=lf, stderr=subprocess.STDOUT)
        except OSError as exc:
            raise TrackError("cv_unavailable", f"could not start cv.track_player ({cmd[0]}): {exc}")
        try:
            while True:
                try:
                    proc.wait(timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if time.monotonic() > deadline:
                    raise TrackError("timeout", f"cv.track_player timed out after {settings.CV_TRACK_TIMEOUT_SECONDS}s")
                pcts = _TQDM.findall(_tail(log_path))
                progress("tracking", 10 + int(min(100, int(pcts[-1])) * 0.85) if pcts else 10)
        except BaseException:
            proc.kill()
            proc.wait()
            raise
    if proc.returncode == EXIT_TARGET_NOT_FOUND:
        raise TrackError("target_not_found", "the selected player could not be found in this video. "
                                             "Pick a clearer frame or box (or check the jersey number).")
    if proc.returncode != 0:
        raise TrackError("cv_failed", f"cv.track_player exited with code {proc.returncode}. Log tail:\n"
                                      f"{_log_tail(log_path)}")
    if not (out_dir / "replay.mp4").is_file():
        raise TrackError("bad_output", "cv.track_player finished but wrote no replay.mp4")


def _tail(path: Path, nbytes: int = 4096) -> str:
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - nbytes))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


# --------------------------------------------------------------------------- output reader (both modes)
STATES = {"tracked", "occluded", "lost", "reacquired"}
STATUSES = {"tracked", "interpolated", "lost"}
PUBLIC_STATES = ("tracked", "occluded", "lost")


def normalize_frame(f: dict, fps: float) -> Optional[dict]:
    """One CV frame -> {frame, t, bbox px|None, conf, state tracked|occluded|lost, raw_state, pitch_x, pitch_y}."""
    frame = _i(f.get("frame"))
    if frame is None or frame < 0:
        return None
    bbox = norm_bbox(f.get("bbox"), f)
    conf = _conf(f.get("confidence", f.get("conf")))
    raw_state = str(f.get("state")).strip().lower() if isinstance(f.get("state"), str) else None
    raw_state = raw_state if raw_state in STATES else None
    if raw_state is not None:  # CV `state` wins when present
        state = {"tracked": "tracked", "reacquired": "tracked", "occluded": "occluded", "lost": "lost"}[raw_state]
    else:
        status = str(f.get("status") or "").strip().lower()
        status = status if status in STATUSES else ("tracked" if bbox else "lost")
        state = {"tracked": "tracked", "interpolated": "occluded", "lost": "lost"}[status]
    if state == "lost" or bbox is None:
        state, bbox, conf = "lost", None, 0.0
    t = _f(f.get("t"))
    return {"frame": frame, "t": round(t, 3) if t is not None else round(frame / fps, 3), "bbox": bbox,
            "conf": conf if conf is not None else 0.0, "state": state, "raw_state": raw_state,
            "pitch_x": _round(_f(f.get("pitch_x")), 2), "pitch_y": _round(_f(f.get("pitch_y")), 2)}


def _round(v: Optional[float], n: int) -> Optional[float]:
    return None if v is None else round(v, n)


def reacquisition_events(states) -> int:
    """Re-acquisitions = recovery EVENTS, not frames: one per lost segment whose next non-occluded frame is tracked
    (lost -> [occluded ...] -> tracked). A trailing lost segment with no recovery counts 0; occluded frames alone
    (no lost frame in the gap) are not a re-acquisition. Accepts public states (tracked/occluded/lost); a CV
    'reacquired' state counts as tracked."""
    count, pending = 0, False
    for st in states:
        if st == "lost":
            pending = True
        elif st in ("tracked", "reacquired"):
            if pending:
                count += 1
            pending = False
        # occluded: keeps a pending gap open
    return count


def _lost_segments(frames: list[dict]) -> list[list[int]]:
    """[[first, last], ...] inclusive runs of state 'lost' (frames is dense and sorted)."""
    segs, start, prev = [], None, None
    for f in frames:
        if f["state"] == "lost":
            if start is None:
                start = f["f"]
            prev = f["f"]
        elif start is not None:
            segs.append([start, prev])
            start = None
    if start is not None:
        segs.append([start, prev])
    return segs


def _clean_segments(segs, total: int) -> Optional[list[list[int]]]:
    """CV lost_segments -> [[first, last], ...] inclusive, 0 <= first <= last < total, sorted; None if unusable."""
    if not isinstance(segs, list):
        return None
    out = []
    for sg in segs:
        if not isinstance(sg, (list, tuple)) or len(sg) != 2:
            return None
        a, b = _i(sg[0]), _i(sg[1])
        if a is None or b is None or a < 0 or b < a or b >= total:
            return None
        out.append([a, b])
    return sorted(out)


def _read_json(path: Path, required: bool):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        if required:
            raise TrackError("bad_output", f"tracking finished but {path.name} is missing")
        return None
    except ValueError as exc:
        if required:
            raise TrackError("bad_output", f"{path.name} is not valid JSON: {exc}")
        return {"_invalid": True}


def read_track_output(out_dir: Path, geo: Geometry, track_id: int, video_id: int, source: str
                      ) -> tuple[dict, dict, Optional[dict]]:
    """track.json (+ meta.json, target_stats.json) -> (public frames document, track meta summary, stats|None).
    Frames document: {track_id, video_id, schema_version, source, fps, width, height, frame_count, target,
    summary, frames:[{f, t, bbox [x,y,w,h] 0-1 | null, conf, state, pitch_x, pitch_y}]} (dense, sorted)."""
    raw = _read_json(out_dir / "track.json", required=True)
    if not isinstance(raw, dict) or not isinstance(raw.get("frames"), list):
        raise TrackError("bad_output", "track.json must be an object with a frames list")
    if not (out_dir / "replay.mp4").is_file():
        raise TrackError("bad_output", "tracking finished but replay.mp4 is missing")
    fps = _f(raw.get("fps")) or geo.fps
    W, H = _i(raw.get("width")) or geo.width, _i(raw.get("height")) or geo.height
    by_frame = {}
    for f in raw["frames"]:
        n = normalize_frame(f, fps) if isinstance(f, dict) else None
        if n is not None:
            by_frame[n["frame"]] = n
    total = _i(raw.get("total_frames")) or geo.total_frames
    if by_frame:
        total = max(total, max(by_frame) + 1)
    frames = []
    for k in range(total):
        n = by_frame.get(k)
        if n is None:
            frames.append({"f": k, "t": round(k / fps, 3), "bbox": None, "conf": 0.0, "state": "lost",
                           "pitch_x": None, "pitch_y": None})
            continue
        frames.append({"f": k, "t": n["t"], "bbox": px_to_norm(n["bbox"], W, H) if n["bbox"] else None,
                       "conf": n["conf"], "state": n["state"], "pitch_x": n["pitch_x"], "pitch_y": n["pitch_y"]})
    tgt = raw.get("target") if isinstance(raw.get("target"), dict) else {}
    track_ids = tgt.get("track_ids")
    target = {"jersey_number": norm_jersey(tgt.get("jersey_number")), "team": norm_team(tgt.get("team")),
              "init_frame": _i(tgt.get("init_frame")),
              "player_uid": None if tgt.get("player_uid") is None else str(tgt.get("player_uid"))[:64],
              "track_ids": [i for i in (_i(x) for x in track_ids) if i is not None] if isinstance(track_ids, list)
              else None}
    meta_raw = _read_json(out_dir / "meta.json", required=False)
    meta_raw = meta_raw if isinstance(meta_raw, dict) else {}
    warnings = meta_raw.get("warnings")
    warnings = [str(w) for w in warnings] if isinstance(warnings, list) else ([str(warnings)] if warnings else [])
    if meta_raw.get("_invalid"):
        warnings.append("meta.json present but not valid JSON")
    if source == "stub":
        warnings.insert(0, "STUB: fake demo track generated by backend/tracking.py")
    counts = {s: sum(1 for f in frames if f["state"] == s) for s in PUBLIC_STATES}
    seen = [f["conf"] for f in frames if f["state"] == "tracked"]
    coverage = round((counts["tracked"] + counts["occluded"]) / max(1, total) * 100, 1)
    segs = _clean_segments(meta_raw.get("lost_segments"), total)   # the CV's own segments win when valid
    if segs is None:
        segs = _lost_segments(frames)
    reacq = _i(meta_raw.get("reacquisition_count"))   # the CV's own count wins when present
    if reacq is None or reacq < 0:
        reacq = reacquisition_events(f["state"] for f in frames)
    summary = {"tracked_frames": counts["tracked"], "occluded_frames": counts["occluded"],
               "lost_frames": counts["lost"],
               "coverage_pct": _round(_f(meta_raw.get("coverage_pct")), 1) if _f(meta_raw.get("coverage_pct"))
               is not None else coverage,
               "avg_conf": round(sum(seen) / len(seen), 3) if seen else None,
               "reacquisition_count": reacq, "lost_segments": [[int(a), int(b)] for a, b in segs]}
    stats = _read_json(out_dir / "target_stats.json", required=False)
    if isinstance(stats, list):
        stats = next((s for s in stats if isinstance(s, dict)), None)
    if not isinstance(stats, dict) or stats.get("_invalid"):
        if isinstance(stats, dict):
            warnings.append("target_stats.json present but not valid JSON")
        stats = None
    else:
        stats = {str(k)[:64]: v for k, v in list(stats.items())[:200]}
    schema_version = raw.get("schema_version")
    api = {"track_id": track_id, "video_id": video_id, "schema_version": schema_version, "source": source,
           "fps": round(fps, 3), "width": W, "height": H, "frame_count": total, "target": target,
           "summary": summary, "frames": frames}
    meta = {"pipeline_version": meta_raw.get("pipeline_version"), "tracker": meta_raw.get("tracker"),
            "schema_version": schema_version, "adapter_source": source, "warnings": warnings,
            "target": target, **summary}
    if _i(meta_raw.get("lost_frames")) is not None:
        meta["cv_lost_frames"] = _i(meta_raw.get("lost_frames"))
    return api, meta, stats


# --------------------------------------------------------------------------- STUB track + replay
def _stub_path(geo: Geometry, t0: float, box: tuple[float, float, float, float], seed: int) -> dict:
    """Smooth motion: centre(t) = clip(c0 + A*sin(2*pi*(t-t0)/P) + v*(t-t0)), same size box. Same formula is
    evaluated in Python (track.json) and by ffmpeg drawbox (replay), so the drawn box matches the JSON."""
    rng = random.Random(seed)
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    return {"w": w, "h": h, "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2, "t0": t0,
            "ax": geo.width * rng.uniform(0.03, 0.08), "px": rng.uniform(4, 9),
            "ay": geo.height * rng.uniform(0.02, 0.05), "py": rng.uniform(5, 11),
            "vx": geo.width * rng.uniform(-0.01, 0.01), "W": geo.width, "H": geo.height}


def _clip(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)


def _stub_box(p: dict, t: float) -> list[float]:
    dt = t - p["t0"]
    cx = _clip(p["cx"] + p["ax"] * math.sin(2 * math.pi * dt / p["px"]) + p["vx"] * dt, p["w"] / 2, p["W"] - p["w"] / 2)
    cy = _clip(p["cy"] + p["ay"] * math.sin(2 * math.pi * dt / p["py"]), p["h"] / 2, p["H"] - p["h"] / 2)
    return [round(cx - p["w"] / 2, 1), round(cy - p["h"] / 2, 1), round(cx + p["w"] / 2, 1), round(cy + p["h"] / 2, 1)]


def _ff_expr(p: dict, axis: str) -> str:
    """ffmpeg expression for the box's top-left x or y at time t (mirrors _stub_box)."""
    dt = f"(t-{p['t0']:.4f})"
    if axis == "x":
        c = f"clip({p['cx']:.3f}+{p['ax']:.3f}*sin(2*PI*{dt}/{p['px']:.4f})+{p['vx']:.4f}*{dt},{p['w'] / 2:.3f}," \
            f"{p['W'] - p['w'] / 2:.3f})"
        return f"{c}-{p['w'] / 2:.3f}"
    c = f"clip({p['cy']:.3f}+{p['ay']:.3f}*sin(2*PI*{dt}/{p['py']:.4f}),{p['h'] / 2:.3f},{p['H'] - p['h'] / 2:.3f})"
    return f"{c}-{p['h'] / 2:.3f}"


def _gap_has_lost(frames: list[dict]) -> bool:
    """True if the current run of non-tracked frames at the end of `frames` contains a lost frame."""
    for f in reversed(frames):
        if f["state"] in ("tracked", "reacquired"):
            return False
        if f["state"] == "lost":
            return True
    return False


def _stub_track(video: MatchVideo, geo: Geometry, target: Target, out_dir: Path,
                progress: Callable[[str, int], None]) -> None:
    rng = random.Random(video.video_id * 7919 + (target.frame or 0) + (target.jersey_number or 0))
    if target.mode == "bbox":
        init_frame, box = target.frame, target.bbox
    else:  # pretend the shirt was found early in the clip
        init_frame = min(geo.total_frames - 1, int(geo.fps * min(1.0, geo.duration / 4)))
        h = geo.height * 0.12
        w = h * 0.42
        x1, y1 = rng.uniform(0, geo.width - w), rng.uniform(geo.height * 0.25, geo.height - h)
        box = (round(x1, 1), round(y1, 1), round(x1 + w, 1), round(y1 + h, 1))
    t0 = geo.t_of(init_frame)
    path = _stub_path(geo, t0, box, rng.randrange(1 << 30))
    progress("tracking", 20)
    # 1-2 lost gaps (never covering the init frame), each with occluded (interpolated) frames around it
    gaps: list[tuple[float, float]] = []
    if geo.duration >= 3:
        for _ in range(rng.randint(1, 2)):
            for _try in range(10):
                a = rng.uniform(0.5, max(0.6, geo.duration - 1.5))
                b = a + rng.uniform(0.4, 1.0)
                if not (a - 0.3 <= t0 <= b + 0.3) and all(b + 0.6 < g[0] or a - 0.6 > g[1] for g in gaps):
                    gaps.append((round(a, 3), round(b, 3)))
                    break
    elif geo.total_frames >= 6:  # short clip: lose the last few frames
        a = geo.t_of(geo.total_frames - 3)
        if a > t0 + 0.05:
            gaps.append((a, geo.duration + 1))
    gaps.sort()
    pad = 0.25
    frames, conf = [], rng.uniform(0.7, 0.9)
    for n in range(geo.total_frames):
        t = geo.t_of(n)
        conf = _clip(conf + rng.uniform(-0.03, 0.03), 0.55, 0.97)
        if any(a <= t <= b for a, b in gaps):
            frames.append({"frame": n, "t": t, "bbox": None, "confidence": None, "state": "lost"})
        elif any(a - pad <= t < a or b < t <= b + pad for a, b in gaps):
            frames.append({"frame": n, "t": t, "bbox": _stub_box(path, t), "confidence": round(rng.uniform(0.25, 0.45), 3),
                           "state": "occluded"})
        else:
            reacq = _gap_has_lost(frames)   # first tracked frame after a gap with a lost frame = 1 event
            frames.append({"frame": n, "t": t, "bbox": _stub_box(path, t), "confidence": round(conf, 3),
                           "state": "reacquired" if reacq else "tracked"})
    jersey = target.jersey_number if target.jersey_number is not None else rng.choice(_stub_roster(video) or [7])
    team = target.team or rng.choice("AB")
    track = {"schema_version": "stub-1", "fps": geo.fps, "width": geo.width, "height": geo.height,
             "total_frames": geo.total_frames,
             "target": {"jersey_number": jersey, "team": team, "init_frame": init_frame,
                        "player_uid": f"stub-{video.video_id}-{init_frame}", "track_ids": [1]},
             "frames": frames}
    (out_dir / "track.json").write_text(json.dumps(track, separators=(",", ":")))
    lost = sum(1 for f in frames if f["state"] == "lost")
    visible_s = (len(frames) - lost) / geo.fps
    minutes = visible_s / 60
    dist_km = minutes * rng.uniform(85, 125) / 1000
    speed = round(rng.uniform(13.5, 21.0), 2)
    meta = {"pipeline_version": "stub-1", "tracker": "stub",
            "lost_frames": lost, "reacquisition_count": reacquisition_events(f["state"] for f in frames),
            "warnings": [] if geo.readable else ["STUB: source video could not be decoded; replay drawn on a blank pitch"]}
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1))
    from metrics_catalog import MIN_RATE_MINUTES
    stats = {"jersey_number": jersey, "team": team, "player_uid": track["target"]["player_uid"],
             "top_speed_mph": speed, "top_speed_kmh": round(speed * 1.60934, 2), "distance_km": round(dist_km, 3),
             "distance_m": round(dist_km * 1000, 1), "minutes_played": round(geo.duration / 60, 2),
             "minutes_played_s": round(geo.duration, 1), "visible_minutes": round(minutes, 2),
             "visible_minutes_s": round(visible_s, 1),
             "distance_per_min_m": round(dist_km * 1000 / minutes, 1) if minutes >= MIN_RATE_MINUTES else None,
             "coverage_pct": round((len(frames) - lost) / max(1, len(frames)) * 100, 1),
             "sprint_count": int(minutes * rng.uniform(0.1, 0.4)),
             "hsr_count": int(minutes * rng.uniform(0.3, 0.8)),
             "injury_risk": rng.choices(["Low", "Medium", "High"], weights=[6, 3, 1])[0]}
    (out_dir / "target_stats.json").write_text(json.dumps(stats, indent=1))
    (out_dir / "STUB_OUTPUT_FAKE_DATA.txt").write_text("Generated by backend/tracking.py STUB, not by the CV model.\n")
    progress("rendering", 50)
    _render_stub_replay(video, geo, path, gaps, pad, out_dir / "replay.mp4", progress)


def _render_stub_replay(video: MatchVideo, geo: Geometry, path: dict, gaps: list[tuple[float, float]], pad: float,
                        dest: Path, progress: Callable[[str, int], None]) -> None:
    src = video_file(video)
    if geo.readable and src and src.is_file():
        inp = ["-i", str(src)]
        keep = ["-fps_mode", "passthrough"]  # same frames/timestamps as the source (frame f <-> t = f / fps)
    else:
        inp = ["-f", "lavfi", "-i", f"color=c={PITCH_GREEN}:s={geo.width}x{geo.height}:r={geo.fps:g}"]
        keep = ["-frames:v", str(geo.total_frames)]
    x, y = _ff_expr(path, "x"), _ff_expr(path, "y")
    lost = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in gaps) or "0"
    interp = "+".join(f"between(t,{a - pad:.3f},{a:.3f})+between(t,{b:.3f},{b + pad:.3f})" for a, b in gaps) or "0"
    bw, bh = max(4, int(round(path["w"]))), max(4, int(round(path["h"])))

    def box(color: str, thick: int, label: str) -> str:  # transparent tile with an outline (alpha needs replace=1)
        return (f"color=c=black@0.0:s={bw}x{bh}:r={geo.fps:g},format=rgba,"
                f"drawbox=x=0:y=0:w={bw}:h={bh}:color={color}:t={thick}:replace=1[{label}]")
    # overlay x/y are evaluated per frame with t = timestamp (drawbox can't move a box over time)
    graph = (f"{box('lime@0.95', 4, 'bt')};{box('yellow@0.9', 3, 'bi')};"
             f"[0:v][bt]overlay=x='{x}':y='{y}':enable='not({lost})*not({interp})':shortest=1[v1];"
             f"[v1][bi]overlay=x='{x}':y='{y}':enable='({interp})*not({lost})':shortest=1,"
             "pad=ceil(iw/2)*2:ceil(ih/2)*2,format=yuv420p[out]")
    cmd = [_ffmpeg(), "-v", "error", "-y", *inp, "-filter_complex", graph, "-map", "[out]", "-an", *keep, *_h264_args(),
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(dest)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    total_us = max(1.0, geo.duration * 1e6)
    last = 0.0
    try:
        for line in proc.stdout:
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                v = _f(line.split("=", 1)[1])
                if v is not None and time.monotonic() - last > 0.5:
                    last = time.monotonic()
                    progress("rendering", 50 + int(min(1.0, v / total_us) * 45))
        proc.wait(timeout=60)
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    err = proc.stderr.read() if proc.stderr else ""
    if proc.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        raise TrackError("cv_failed", f"ffmpeg could not render the stub replay (code {proc.returncode}): {err[-400:]}")
