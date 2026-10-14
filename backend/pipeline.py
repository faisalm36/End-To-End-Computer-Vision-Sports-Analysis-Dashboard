"""Adapter between the backend and the CV pipeline from GitHub PR #1 (cv/run_pipeline.py).

Contract with the CV pipeline (branch cursor/soccer-cv-pipeline-236d, confirmed with the CV engineer):
  invoke : cd <repo root> && PYTHONPATH=<repo root> <python> -m cv.run_pipeline --video <file> --out <dir>
               [--calibration <json>] [--device auto|cuda|mps|cpu] [--model <weights>] [...]
  output : <dir>/tracking_detections.json -> list of
             {frame, timestamp, track_id (-1 = ball), class ("player"|"ball"),
              bbox_x1, bbox_y1, bbox_x2, bbox_y2, confidence, pitch_x, pitch_y, jersey_number,
              team (0|1|null, coming soon), role ("player"|"goalkeeper"|"referee"|"ball", coming soon)}
           <dir>/player_match_stats.json  -> list of
             {track_id, jersey_number, top_speed_mph|null, distance_km|null, injury_risk,
              high_speed_distance_km, sprint_distance_km, sprint_count, team?, role?}
             (speed/distance are null when no calibration is given)
             v1.2.0 adds top_speed_kmh, minutes_played, visible_minutes, coverage_pct, distance_per_min_m,
              avg_pitch_x/y, hsr_count, hi_efforts_count, zone_{walk,jog,run,hsr,sprint}_km,
              accel_count_high, decel_count_high (all null without calibration)
           <dir>/meta.json -> {fps, frame_count, duration_s, resolution, model, device, calibration,
              pipeline_version, runtime_s, warnings: [...], speed_preset, hsr_threshold_kmh,
              sprint_threshold_kmh, zone_edges_kmh {walk, jog, run, hsr}}   (thresholds: v1.1.2+ / v1.2.0)
           <dir>/heatmaps.json (v1.2.0, optional) -> {"<track_id>": [[seconds x 21 cols] x 14 rows]}
  Existing field names won't change; new fields may appear. Every field is read defensively.
  CV PR #2 (v2.0, not merged yet): heatmaps.json is always written ({} without calibration -> backend grids, no
  warning); per-player distance_m / minutes_played_s / visible_minutes_s are preferred over the rounded km / minutes
  when present; player_uid / contributing_track_ids / detected_frames / total_frames are accepted and ignored for now.
  distance_per_min is null when the player's minutes (tracked, else played) are below mc.MIN_RATE_MINUTES.

Modes (settings.CV_PIPELINE_MODE):
  auto : run the real pipeline if CV_PIPELINE_PATH exists; else the STUB if CV_PIPELINE_STUB=true;
         else fail the video with a clear error_message.
  real : always the real pipeline (fails if missing).
  stub : always the STUB (FAKE demo data; recorded as adapter_source="stub" in pipeline_meta).
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from config import BASE_DIR, settings
from database import SessionLocal
import metrics_catalog as mc
from models import Match, MatchVideo, Player, PlayerHeatmap, PlayerMatchMetric, PlayerMatchStat, TrackingDetection
from stats import RANK_RISK, RISK_RANK

FATIGUE_SCORE = {"Low": 0.0, "Medium": 50.0, "High": 100.0}
MPH_TO_KMH = 1.609344


def _fatigue(risk: Optional[str]) -> Optional[Decimal]:
    v = FATIGUE_SCORE.get(risk) if risk else None
    return None if v is None else Decimal(str(v))


def _fmt_resolution(meta: dict) -> Optional[str]:
    r = meta.get("resolution") if isinstance(meta, dict) else None
    if isinstance(r, str) and r.strip():
        return r.strip()[:20]
    if isinstance(r, (list, tuple)) and len(r) >= 2:
        try:
            return f"{int(r[0])}x{int(r[1])}"[:20]
        except (TypeError, ValueError):
            return None
    return None


def _bbox_center_size(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float, float, float]:
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0, abs(x2 - x1), abs(y2 - y1)

from timeutil import utcnow

log = logging.getLogger("pipeline")
INSERT_CHUNK = 5000
SKIP_ROLES = {"referee"}


class PipelineError(RuntimeError):
    pass


@dataclass
class PipelineOutput:
    detections: list[dict]
    player_stats: list[dict]
    source: str  # "real" | "stub"
    meta: dict = field(default_factory=dict)
    adapter_warnings: list[str] = field(default_factory=list)  # added by ingest_output (unknown metric keys, ...)
    heatmaps: dict = field(default_factory=dict)  # heatmaps.json: {"<track_id>": [[seconds]]} (pipeline >= 1.2.0)
    adapter_metrics: dict = field(default_factory=dict)  # set by ingest_output: which source each metric used
    risk_gate: dict = field(default_factory=dict)  # set by ingest_output: facts the risk gates need (risk_service)


# --------------------------------------------------------------------------- progress
STAGES = ("queued", "detect", "track", "ocr", "metrics", "ingest", "done", "failed")


class VideoDeleted(Exception):
    """The match_videos row was deleted while we were working on it."""


def set_progress(video_id: int, stage: str, progress: int) -> bool:
    """Persist stage/progress (never moves backwards). Returns False if the row is gone."""
    db = SessionLocal()
    try:
        v = db.get(MatchVideo, video_id)
        if v is None:
            return False
        progress = max(0, min(100, int(progress)))
        if progress >= (v.progress or 0) or stage in ("done", "failed"):
            v.stage, v.progress = stage, progress
            db.commit()
        return True
    finally:
        db.close()


_TQDM = re.compile(r"Processing frames:\s+(\d{1,3})%")


def stage_from_log(text: str) -> Optional[tuple[str, int]]:
    """Best-effort stage hints from the CV pipeline's console output (tqdm bar + phase messages)."""
    if "Calculating player statistics" in text:
        return "metrics", 78
    if "Finalizing jersey numbers" in text:
        return "ocr", 75
    if "Finalizing team and role" in text:
        return "track", 72
    pcts = _TQDM.findall(text)
    if pcts:
        return "detect", 10 + int(min(100, int(pcts[-1])) * 0.6)  # 10..70 while frames are processed
    return None


def _cleanup_outputs(video_id: int) -> None:
    shutil.rmtree(Path(settings.CV_OUTPUT_DIR) / f"video_{video_id}", ignore_errors=True)


# --------------------------------------------------------------------------- entry point
def process_video(video_id: int) -> None:
    """BackgroundTask: queued -> processing -> done | failed. Never raises.
    Tolerates the row being deleted (DELETE /api/videos/{id}) at any point."""
    db = SessionLocal()
    try:
        video = db.get(MatchVideo, video_id)
        if video is None:
            return
        video.processing_status = "processing"
        video.stage, video.progress = "detect", 10
        video.error_message = None
        db.commit()
        started = time.monotonic()
        try:
            _maybe_thumbnail(db, video)
            output = run_pipeline(video)
            if not set_progress(video_id, "metrics", 80):
                raise VideoDeleted()
            if not set_progress(video_id, "ingest", 90):
                raise VideoDeleted()
            db.expire_all()
            video = db.get(MatchVideo, video_id)
            if video is None:
                raise VideoDeleted()
            ingest_output(db, video, output)
            video.pipeline_meta = json.dumps(_meta_summary(output, time.monotonic() - started), default=str)
            video.processing_status = "done"
            video.stage, video.progress = "done", 100
            video.error_message = None
            video.processed_at = utcnow()
            db.commit()
            log.info("video %s processed (%s): %d detections, %d stat rows",
                     video_id, output.source, len(output.detections), len(output.player_stats))
            _score_risk(db, video_id)
        except VideoDeleted:
            db.rollback()
            log.info("video %s was deleted during processing; stopping", video_id)
            _cleanup_outputs(video_id)
        except Exception as exc:  # noqa: BLE001 - record any failure on the row
            db.rollback()
            db.expire_all()
            video = db.get(MatchVideo, video_id)
            if video is None:  # deleted mid-ingest (FK errors etc.) - nothing to record
                log.info("video %s was deleted during processing; stopping", video_id)
                _cleanup_outputs(video_id)
                return
            log.exception("video %s failed", video_id)
            video.processing_status = "failed"
            video.stage = "failed"
            video.error_message = f"{type(exc).__name__}: {exc}"[:4000]
            video.processed_at = utcnow()
            db.commit()
    finally:
        db.close()


def _maybe_thumbnail(db: Session, video: MatchVideo) -> None:
    from thumbnails import make_thumbnail
    src = Path(video.file_path)
    if not src.is_absolute():
        src = BASE_DIR / src
    thumb = make_thumbnail(src, video.video_id)
    if thumb is not None:
        try:
            video.thumbnail_path = str(thumb.resolve().relative_to(BASE_DIR))
        except ValueError:
            video.thumbnail_path = str(thumb.resolve())
        db.commit()


def _meta_summary(out: PipelineOutput, adapter_runtime_s: float) -> dict:
    """What we keep in match_videos.pipeline_meta: the pipeline's meta.json plus adapter info."""
    meta = dict(out.meta) if isinstance(out.meta, dict) else {}
    warnings = meta.get("warnings")
    meta["warnings"] = warnings if isinstance(warnings, list) else ([warnings] if warnings else [])
    meta["adapter_source"] = out.source
    meta["adapter_runtime_s"] = round(adapter_runtime_s, 2)
    meta["detections_count"] = len(out.detections)
    meta["player_stats_count"] = len(out.player_stats)
    if out.player_stats and all(_opt_float(s.get("top_speed_mph")) is None for s in out.player_stats):
        meta["warnings"].append("No speed/distance in pipeline output (no calibration?)")
    cal = str(meta.get("calibration") or "")
    already = any("default calibration" in str(w).lower() or "default_calibration" in str(w).lower()
                  for w in meta["warnings"])
    if cal.endswith("default_calibration.json") and not already:
        # v1.1.0 fell back silently; v1.1.1+ puts its own warning in meta.warnings (then we don't duplicate it)
        meta["warnings"].append("Pipeline used cv/config/default_calibration.json (generic); speed/distance are approximate")
    meta["warnings"].extend(w for w in out.adapter_warnings if w not in meta["warnings"])
    if out.adapter_metrics:
        meta["adapter_metrics"] = out.adapter_metrics
    if out.risk_gate:
        meta["risk_gate"] = out.risk_gate
    return meta


def repo_root() -> Path:
    """CV_PIPELINE_PATH points at <repo>/cv/run_pipeline.py (or at the cv/ dir, or the repo root)."""
    p = Path(settings.CV_PIPELINE_PATH).expanduser().resolve()
    if p.name == "run_pipeline.py":
        return p.parent.parent
    if p.name == "cv":
        return p.parent
    return p


def pipeline_available() -> bool:
    return (repo_root() / "cv" / "run_pipeline.py").is_file()


def resolve_mode() -> str:
    mode = settings.CV_PIPELINE_MODE.lower()
    if mode in {"real", "stub"}:
        return mode
    if pipeline_available():
        return "real"
    return "stub" if settings.CV_PIPELINE_STUB else "missing"


def run_pipeline(video: MatchVideo) -> PipelineOutput:
    video_path = Path(video.file_path)
    if not video_path.is_absolute():
        video_path = BASE_DIR / video_path
    out_dir = Path(settings.CV_OUTPUT_DIR) / f"video_{video.video_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in ("tracking_detections.json", "player_match_stats.json", "meta.json", "heatmaps.json"):
        (out_dir / stale).unlink(missing_ok=True)

    mode = resolve_mode()
    if mode == "missing":
        raise PipelineError(
            f"CV pipeline not found at {repo_root() / 'cv' / 'run_pipeline.py'}. Set CV_PIPELINE_PATH to "
            "cv/run_pipeline.py (PR #1), or set CV_PIPELINE_STUB=true to generate fake demo stats."
        )
    if mode == "stub":
        _write_stub_output(video, out_dir)
    else:
        _run_real(video_path, out_dir, video.video_id)
    detections, stats, meta = _read_output(out_dir)
    heatmaps, hm_warning = _read_heatmaps(out_dir)
    out = PipelineOutput(detections, stats, mode, meta, heatmaps=heatmaps)
    if hm_warning:
        out.adapter_warnings.append(hm_warning)
    return out


# --------------------------------------------------------------------------- real pipeline
def build_command(video_path: Path, out_dir: Path) -> list[str]:
    cmd = [settings.CV_PYTHON or sys.executable, "-m", "cv.run_pipeline",
           "--video", str(video_path.resolve()), "--out", str(out_dir.resolve()),
           "--device", settings.CV_DEVICE]
    if settings.CV_CALIBRATION_PATH:
        cmd += ["--calibration", str(Path(settings.CV_CALIBRATION_PATH).expanduser().resolve())]
    if settings.CV_MODEL:
        cmd += ["--model", settings.CV_MODEL]
    cmd += shlex.split(settings.CV_EXTRA_ARGS)
    return cmd


def _run_real(video_path: Path, out_dir: Path, video_id: Optional[int] = None) -> None:
    root = repo_root()
    if not (root / "cv" / "run_pipeline.py").is_file():
        raise PipelineError(f"CV pipeline not found at {root / 'cv' / 'run_pipeline.py'}")
    if not video_path.is_file():
        raise PipelineError(f"Uploaded file missing: {video_path}")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(root), env.get("PYTHONPATH", "")]))
    env.setdefault("PYTHONUNBUFFERED", "1")
    cmd = build_command(video_path, out_dir)
    log_path = out_dir / "pipeline.log"
    log.info("running CV pipeline (cwd=%s): %s", root, shlex.join(cmd))
    deadline = time.monotonic() + settings.CV_TIMEOUT_SECONDS
    with log_path.open("w") as lf:
        lf.write(f"# cwd={root}\n$ " + shlex.join(cmd) + "\n")
        lf.flush()
        try:
            # cwd = repo root, as the CV engineer specified (YOLO weights auto-download here; *.pt is gitignored)
            proc = subprocess.Popen(cmd, cwd=root, env=env, stdout=lf, stderr=subprocess.STDOUT)
        except OSError as exc:
            raise PipelineError(f"Could not start CV pipeline ({cmd[0]}): {exc}")
        last_hint = None
        while True:
            try:
                proc.wait(timeout=2)
                break
            except subprocess.TimeoutExpired:
                pass
            if time.monotonic() > deadline:
                proc.kill()
                proc.wait()
                raise PipelineError(f"CV pipeline timed out after {settings.CV_TIMEOUT_SECONDS}s (log: {log_path})")
            if video_id is None:
                continue
            hint = stage_from_log(_tail(log_path))
            if hint and hint != last_hint:
                last_hint = hint
            if not set_progress(video_id, *(last_hint or ("detect", 10))):
                proc.kill()
                proc.wait()
                raise VideoDeleted()
    if proc.returncode != 0:
        tail = "\n".join(log_path.read_text(errors="replace").replace("\r", "\n").splitlines()[-15:])
        raise PipelineError(f"CV pipeline exited with code {proc.returncode}. Log tail:\n{tail}")


def _tail(path: Path, nbytes: int = 8192) -> str:
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - nbytes))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _read_output(out_dir: Path) -> tuple[list[dict], list[dict], dict]:
    try:
        detections = json.loads((out_dir / "tracking_detections.json").read_text())
        stats = json.loads((out_dir / "player_match_stats.json").read_text())
    except FileNotFoundError as exc:
        raise PipelineError(f"CV pipeline finished but output is missing: {exc.filename}")
    except json.JSONDecodeError as exc:
        raise PipelineError(f"CV pipeline output is not valid JSON: {exc}")
    if not isinstance(detections, list) or not isinstance(stats, list):
        raise PipelineError("CV pipeline output JSON must be lists")
    meta: dict = {}
    meta_path = out_dir / "meta.json"
    if meta_path.is_file():  # optional; a broken meta.json shouldn't fail the video
        try:
            loaded = json.loads(meta_path.read_text())
            meta = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            meta = {"warnings": ["meta.json present but not valid JSON"]}
    return ([d for d in detections if isinstance(d, dict)],
            [s for s in stats if isinstance(s, dict)], meta)


def _read_heatmaps(out_dir: Path) -> tuple[dict, Optional[str]]:
    """Optional heatmaps.json (v1.2.0). Broken file -> ({}, warning); the backend grid is used instead."""
    path = out_dir / "heatmaps.json"
    if not path.is_file():
        return {}, None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}, "heatmaps.json present but not valid JSON; using backend heatmaps"
    if not isinstance(data, dict):
        return {}, "heatmaps.json is not an object keyed by track_id; using backend heatmaps"
    return {str(k): v for k, v in data.items()}, None


# --------------------------------------------------------------------------- STUB
STUB_DEFAULT_DURATION_S = 1.0   # when the clip can't be probed (tests upload fake bytes)
STUB_MAX_SAMPLES = 300          # detection samples per track (long clips use a bigger frame stride)


def probe_video(path: Path) -> Optional[tuple[float, float]]:
    """(duration_s, fps) via ffprobe, else cv2; None if neither works. Never raises."""
    exe = shutil.which("ffprobe")
    if exe:
        try:
            r = subprocess.run([exe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=avg_frame_rate,r_frame_rate,duration:format=duration", "-of", "json",
                                str(path)], capture_output=True, text=True, timeout=30, check=False)
            data = json.loads(r.stdout or "{}")
            st = (data.get("streams") or [{}])[0]
            dur = _opt_float(st.get("duration")) or _opt_float((data.get("format") or {}).get("duration"))
            fps = None
            for k in ("avg_frame_rate", "r_frame_rate"):
                num, _, den = str(st.get(k) or "").partition("/")
                if _opt_float(num) and _opt_float(den or "1"):
                    fps = _opt_float(num) / _opt_float(den or "1")
                    break
            if dur and dur > 0 and fps and 0 < fps <= 240:
                return dur, fps
        except (OSError, subprocess.SubprocessError, ValueError, IndexError, AttributeError):
            pass
    try:
        import cv2  # optional
        cap = cv2.VideoCapture(str(path))
        try:
            fps, n = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT)
        finally:
            cap.release()
        if fps and 0 < fps <= 240 and n and n > 0:
            return n / fps, fps
    except Exception:  # noqa: BLE001
        pass
    return None


def _write_stub_output(video: MatchVideo, out_dir: Path) -> None:
    """STUB - FAKE DEMO DATA. Writes files in the real pipeline's format (v1.2 keys + PR #2's distance_m /
    minutes_played_s / visible_minutes_s). Values are physically consistent with the clip: duration from the uploaded
    file (ffprobe/cv2; 1 s if it can't be read), minutes from the frames each player is visible, distance from a
    plausible 85-125 m/min, distance_per_min null under mc.MIN_RATE_MINUTES."""
    log.warning("CV PIPELINE STUB used for video %s: stats are FAKE demo data", video.video_id)
    rng = random.Random(video.video_id)
    src = Path(video.file_path)
    probed = probe_video(src if src.is_absolute() else BASE_DIR / src)
    duration, fps = probed if probed else (STUB_DEFAULT_DURATION_S, 30.0)
    frame_count = max(1, int(round(duration * fps)))
    stride = max(3, -(-frame_count // STUB_MAX_SAMPLES))
    sample_frames = list(range(0, frame_count, stride))
    db = SessionLocal()
    try:
        match = db.get(Match, video.match_id)
        players = []
        for team_idx, team_id in ((0, match.home_team_id), (1, match.away_team_id)):
            for p in db.scalars(select(Player).where(Player.team_id == team_id)).all():
                if p.jersey_number is not None:
                    players.append((team_idx, p.jersey_number))
    finally:
        db.close()
    players = sorted(set(players))[:10] or [(0, n) for n in range(1, 9)]
    detections, stats, heatmaps = [], [], {}
    tracks = [(i, team, jersey, "player") for i, (team, jersey) in enumerate(players, start=1)]
    tracks.append((len(tracks) + 1, None, None, "referee"))  # exercises the referee skip
    for track_id, team, jersey, role in tracks:
        x, y = rng.uniform(200, 1700), rng.uniform(150, 900)
        grid = [[0.0] * 21 for _ in range(14)]
        pxs, pys = [], []
        # visible window (enters late / leaves early) with ~10% gaps; always >= 2 samples when the clip has them
        n = len(sample_frames)
        lo, hi = int(n * rng.uniform(0, 0.15)), max(1, int(round(n * rng.uniform(0.85, 1.0))))
        seen = [f for i, f in enumerate(sample_frames[lo:hi]) if i in (0, hi - lo - 1) or rng.random() > 0.1] \
            or sample_frames[:2]
        for frame in seen:
            px, py = min(max(x / 18.3, 0), 105), min(max(y / 15.9, 0), 68)
            pxs.append(px)
            pys.append(py)
            grid[min(int(py / 68 * 14), 13)][min(int(px / 105 * 21), 20)] += round(stride / fps, 3)
            detections.append({
                "frame": frame, "timestamp": round(frame / fps, 3), "track_id": track_id, "class": "player",
                "bbox_x1": round(x, 2), "bbox_y1": round(y, 2), "bbox_x2": round(x + 40, 2),
                "bbox_y2": round(y + 90, 2), "confidence": round(rng.uniform(0.6, 0.97), 3),
                "pitch_x": round(x / 18.3, 2), "pitch_y": round(y / 15.9, 2), "jersey_number": jersey,
                "team": team, "role": role,
            })
            x = min(max(x + rng.uniform(-8, 12), 0), 1900)
        played_s = min(duration, (seen[-1] - seen[0]) / fps)              # first to last seen (pipeline definition)
        visible_s = min(duration, len(seen) * stride / fps)               # each sample stands for `stride` frames
        visible_min = visible_s / 60.0
        dist = visible_min * rng.uniform(85, 125) / 1000.0                # km
        heatmaps[str(track_id)] = grid
        zones = [rng.uniform(0.2, 1) for _ in range(5)]
        zones = [round(dist * z / sum(zones), 4) for z in zones]
        speed = round(rng.uniform(13.5, 22.0), 2)
        hsr_n, spr_n = int(round(visible_min * rng.uniform(0.3, 0.8))), int(round(visible_min * rng.uniform(0.1, 0.4)))
        dpm = distance_per_min(dist, visible_min)
        stats.append({
            "track_id": track_id, "jersey_number": jersey, "team": team, "role": role,
            "top_speed_mph": speed, "top_speed_kmh": round(speed * 1.60934, 2),
            "distance_km": round(dist, 3), "distance_m": round(dist * 1000, 1),
            "injury_risk": rng.choices(["Low", "Medium", "High"], weights=[6, 3, 1])[0],
            "high_speed_distance_km": round(dist * rng.uniform(0.06, 0.12), 3),
            "sprint_distance_km": round(dist * rng.uniform(0.02, 0.05), 3),
            "sprint_count": spr_n, "hsr_count": hsr_n, "hi_efforts_count": hsr_n + spr_n,
            "minutes_played": round(played_s / 60.0, 2), "minutes_played_s": round(played_s, 1),
            "visible_minutes": round(visible_min, 2), "visible_minutes_s": round(visible_s, 1),
            "distance_per_min_m": None if dpm is None else round(dpm, 2),
            "avg_pitch_x": round(sum(pxs) / len(pxs), 2), "avg_pitch_y": round(sum(pys) / len(pys), 2),
            "coverage_pct": round(min(100.0, visible_s / duration * 100.0), 2),
            "zone_walk_km": zones[0], "zone_jog_km": zones[1], "zone_run_km": zones[2], "zone_hsr_km": zones[3],
            "zone_sprint_km": zones[4],
            "accel_count_high": int(round(visible_min * rng.uniform(0.2, 0.6))),
            "decel_count_high": int(round(visible_min * rng.uniform(0.2, 0.6))),
        })
    detections.append({"frame": 0, "timestamp": 0.0, "track_id": -1, "class": "ball", "role": "ball",
                       "bbox_x1": 950.0, "bbox_y1": 530.0, "bbox_x2": 962.0, "bbox_y2": 542.0,
                       "confidence": 0.41, "pitch_x": 52.5, "pitch_y": 34.0, "jersey_number": None, "team": None})
    th = mc.DEFAULT_SPEED_THRESHOLDS
    meta = {"fps": round(fps, 3), "frame_count": frame_count, "duration_s": round(duration, 3),
            "resolution": [1920, 1080], "model": "stub", "device": "none", "calibration": None,
            "pipeline_version": "stub-1", "runtime_s": 0.0,
            "warnings": ["STUB: fake demo data generated by backend/pipeline.py"]
                        + ([] if probed else [f"STUB: clip length unknown; assumed {STUB_DEFAULT_DURATION_S:g} s"]),
            "speed_preset": th["preset"], "hsr_threshold_kmh": th["hsr_kmh"], "sprint_threshold_kmh": th["sprint_kmh"],
            "zone_edges_kmh": dict(th["zone_edges_kmh"])}
    (out_dir / "tracking_detections.json").write_text(json.dumps(detections, indent=2))
    (out_dir / "player_match_stats.json").write_text(json.dumps(stats, indent=2))
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    (out_dir / "heatmaps.json").write_text(json.dumps(heatmaps))
    (out_dir / "STUB_OUTPUT_FAKE_DATA.txt").write_text("Generated by backend/pipeline.py STUB, not by the CV model.\n")


# --------------------------------------------------------------------------- ingest helpers
def _opt_int(v):
    if isinstance(v, bool):
        return None
    try:
        return None if v is None or v == "" else int(v)
    except (TypeError, ValueError):
        return None


def _opt_float(v):
    try:
        f = None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None
    return None if f is None or f != f else f  # NaN (pandas-style) -> None


def team_side(team) -> Optional[str]:
    """Map the pipeline's `team` label to our side. Currently 0 = home, 1 = away (per CV engineer).
    Change here if the CV pipeline's convention changes."""
    if isinstance(team, str) and team.strip().upper() in ("A", "B"):  # PR #2 docs show "A"/"B" (code emits 0/1)
        return {"A": "home", "B": "away"}[team.strip().upper()]
    t = _opt_int(team)
    return {0: "home", 1: "away"}.get(t) if t is not None else None


def _role(row: dict) -> Optional[str]:
    r = row.get("role")
    return str(r).strip().lower() if r not in (None, "") else None


def _placeholder_player(db: Session, team_id: int, jersey: Optional[int], track_id: int, video_id: int) -> Player:
    # Jersey placeholders are reused across videos (same shirt on same team is likely the same person);
    # track-only placeholders are per video because track ids restart in every video.
    last = f"#{jersey}" if jersey is not None else f"Track {track_id} (video {video_id})"
    p = db.scalar(select(Player).where(Player.team_id == team_id, Player.first_name == "Unknown",
                                       Player.last_name == last))
    if p is None:
        p = Player(team_id=team_id, first_name="Unknown", last_name=last[:50], jersey_number=None,
                   position="Unassigned")
        db.add(p)
        db.flush()
    return p


def _merge_max(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return b if a is None else a if b is None else max(a, b)


def _merge_sum(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return b if a is None else a if b is None else a + b


def _collect_metrics(s: dict, acc: dict, unknown: set) -> None:
    """Pull extended metrics out of one player_match_stats.json row into acc (merging fragmented tracks)."""
    for raw_key, raw_val in s.items():
        key = mc.PIPELINE_ALIASES.get(raw_key)
        if key is None:
            if raw_key not in mc.KNOWN_STAT_KEYS and isinstance(raw_val, (int, float)) and not isinstance(raw_val, bool):
                unknown.add(raw_key)
            continue
        val = _opt_float(raw_val)
        acc[key] = mc.merge(key, acc.get(key), val) if key in acc else val
    hsr_n = _opt_float(s.get("hsr_count"))
    spr_n = _opt_float(s.get("sprint_count"))
    if ("high_intensity_efforts" not in s and "hi_efforts_count" not in s
            and hsr_n is not None and spr_n is not None):
        acc["high_intensity_efforts"] = mc.merge("high_intensity_efforts", acc.get("high_intensity_efforts"),
                                                 hsr_n + spr_n)


def _calibration_file(meta: dict) -> Optional[Path]:
    cal = meta.get("calibration") if isinstance(meta, dict) else None
    if not cal or not isinstance(cal, str) or cal.lower() == "none":
        return None
    p = Path(cal)
    if not p.is_absolute():
        p = repo_root() / p
    return p if p.is_file() else None


def speed_thresholds(meta: dict) -> Optional[dict]:
    """{preset, hsr_kmh, sprint_kmh, zone_edges_kmh} from meta.json (v1.1.2+ / v1.2.0), or None if absent."""
    if not isinstance(meta, dict):
        return None
    edges = meta.get("zone_edges_kmh")
    edges = {k: _opt_float(v) for k, v in edges.items()} if isinstance(edges, dict) else None
    out = {"preset": meta.get("speed_preset") if isinstance(meta.get("speed_preset"), str) else None,
           "hsr_kmh": _opt_float(meta.get("hsr_threshold_kmh")),
           "sprint_kmh": _opt_float(meta.get("sprint_threshold_kmh")),
           "zone_edges_kmh": edges}
    return out if any(v is not None for v in out.values()) else None


def effective_speed_thresholds(meta) -> dict:
    """speed_thresholds(meta) with gaps filled from mc.DEFAULT_SPEED_THRESHOLDS (values rounded to 0.1 km/h).
    source: "pipeline" (all from meta.json) | "default" (none: seeded/older rows) | "mixed"."""
    got = speed_thresholds(meta) or {}
    d = mc.DEFAULT_SPEED_THRESHOLDS
    got_edges = {k: v for k, v in (got.get("zone_edges_kmh") or {}).items() if v is not None}
    r1 = lambda v: None if v is None else round(float(v), 1)  # noqa: E731
    edges = {k: r1(got_edges.get(k, v)) for k, v in d["zone_edges_kmh"].items()}
    edges.update({k: r1(v) for k, v in got_edges.items() if k not in edges})
    parts = [got.get("preset"), got.get("hsr_kmh"), got.get("sprint_kmh")] + [got_edges.get(k) for k in d["zone_edges_kmh"]]
    n = sum(v is not None for v in parts)
    return {"preset": got.get("preset") or d["preset"],
            "hsr_kmh": r1(got["hsr_kmh"] if got.get("hsr_kmh") is not None else d["hsr_kmh"]),
            "sprint_kmh": r1(got["sprint_kmh"] if got.get("sprint_kmh") is not None else d["sprint_kmh"]),
            "zone_edges_kmh": edges,
            "source": "pipeline" if n == len(parts) else "default" if n == 0 else "mixed"}


def _track_minutes(tracks: list[dict], key: str) -> Optional[float]:
    """Sum of a per-track minutes value; PR #2's <key>_s (seconds, 0.1 s precision) wins over the rounded minutes."""
    vals = []
    for t in tracks:
        sec = _opt_float(t.get(f"{key}_s"))
        v = sec / 60.0 if sec is not None and sec >= 0 else _opt_float(t.get(key))
        if v is not None and v >= 0:
            vals.append(v)
    return sum(vals) if vals else None


def _track_distance_km(tracks: list[dict]) -> Optional[float]:
    """Distance for rates: distance_m (PR #2, 0.1 m) when given, else distance_km; only tracks whose distance_km is
    set count (PR #2 nulls distance_km without calibration but may leave distance_m)."""
    vals = []
    for t in tracks:
        km = _opt_float(t.get("distance_km"))
        if km is None:
            continue
        m = _opt_float(t.get("distance_m"))
        vals.append(m / 1000.0 if m is not None and m >= 0 else km)
    return sum(vals) if vals else None


def distance_per_min(distance_km: Optional[float], minutes: Optional[float]) -> Optional[float]:
    """m/min, or None when either is unknown or minutes < mc.MIN_RATE_MINUTES (never divides by ~0)."""
    if distance_km is None or minutes is None or minutes < mc.MIN_RATE_MINUTES:
        return None
    return distance_km * 1000.0 / minutes


def _track_sum(tracks: list[dict], key: str) -> Optional[float]:
    vals = [v for v in (_opt_float(t.get(key)) for t in tracks) if v is not None]
    return sum(vals) if vals else None


def _store_metrics(db: Session, out: PipelineOutput, merged: dict, stat_rows: dict, det_rows: list[dict]) -> None:
    """Per player (tracks already merged): extended metrics + heatmap.
    Preference: pipeline v1.2 per-track values > backend estimates (video length, detections)."""
    meta = out.meta if isinstance(out.meta, dict) else {}
    duration = _opt_float(meta.get("duration_s"))
    video_min = duration / 60.0 if duration and duration > 0 else None
    fps = _opt_float(meta.get("fps"))
    length, width = mc.pitch_dims(_calibration_file(meta))
    points: dict[int, list] = defaultdict(list)
    for r in det_rows:
        if r["player_id"] is not None and r["pitch_x"] is not None and r["pitch_y"] is not None:
            points[r["player_id"]].append((r["pitch_x"], r["pitch_y"]))
    used = {"minutes_played": Counter(), "avg_position": Counter(), "heatmap": Counter()}
    metric_rows = []
    for pid, m in merged.items():
        stat, tracks = stat_rows[pid], m.get("tracks", [])
        vals = dict(m["extra"])
        # minutes: pipeline (first-to-last seen / tracked) > video length
        # minutes_played: ONLY the pipeline's own value (minutes_played_s / minutes_played). Never the clip length
        # (v0.7.0 fix: duration_s/60 is not time on the pitch); null when the CV didn't provide it.
        played, visible = _track_minutes(tracks, "minutes_played"), _track_minutes(tracks, "visible_minutes")
        if played is not None:
            used["minutes_played"]["pipeline"] += 1
        if video_min is not None:  # fragments are added up; never more than the clip
            played = None if played is None else min(played, video_min)
            visible = None if visible is None else min(visible, video_min)
        vals["minutes_played"] = None if played is None else round(played, 3)
        vals["visible_minutes"] = None if visible is None else round(visible, 3)
        cov = _track_sum(tracks, "coverage_pct")
        vals["coverage_pct"] = None if cov is None else round(min(cov, 100.0), 2)
        # distance per minute (m/min) = distance / tracked minutes (pipeline's definition), else / minutes played.
        # Null below mc.MIN_RATE_MINUTES (also overrides the pipeline's own value). One track: the pipeline's value
        # (computed before it rounds distance/minutes); fragments or no pipeline value: recomputed.
        den = visible if visible is not None else played
        dpm = None
        if den is not None and den >= mc.MIN_RATE_MINUTES:
            dpm = _opt_float(tracks[0].get("distance_per_min_m")) if len(tracks) == 1 else None
            if dpm is None:
                dist_km = _track_distance_km(tracks)
                dpm = distance_per_min(dist_km if dist_km is not None else m["dist"], den)
        vals["distance_per_min"] = None if dpm is None else round(dpm, 2)
        kmh = [v for v in (_opt_float(t.get("top_speed_kmh")) for t in tracks) if v is not None]
        vals["top_speed_kmh"] = (round(max(kmh), 2) if kmh else
                                 None if m["speed"] is None else round(m["speed"] * 1.60934, 2))
        # average position: pipeline (weighted by tracked minutes) > mean of mapped detections
        pos = [(_opt_float(t.get("avg_pitch_x")), _opt_float(t.get("avg_pitch_y")),
                _opt_float(t.get("visible_minutes"))) for t in tracks]
        pos = [(x, y, 1.0 if w is None else w) for x, y, w in pos if x is not None and y is not None]
        if pos and sum(p[2] for p in pos) <= 0:
            pos = [(x, y, 1.0) for x, y, _ in pos]
        cells, samples, mean = mc.heatmap(points.get(pid, []), length, width)
        if pos:
            w = sum(p[2] for p in pos)
            vals["avg_pitch_x"] = round(sum(p[0] * p[2] for p in pos) / w, 2)
            vals["avg_pitch_y"] = round(sum(p[1] * p[2] for p in pos) / w, 2)
            used["avg_position"]["pipeline"] += 1
        elif mean is not None:
            vals["avg_pitch_x"], vals["avg_pitch_y"] = round(mean[0], 2), round(mean[1], 2)
            used["avg_position"]["detections"] += 1
        # heatmap: pipeline heatmaps.json (21x14 seconds) > backend grid from detections (12x8 counts)
        grids = [g for g in (out.heatmaps.get(str(_opt_int(t.get("track_id")))) for t in tracks) if g is not None]
        dims = {mc.valid_grid(g) for g in grids}
        if grids and len(dims) == 1 and None not in dims:
            cols, rows_n = dims.pop()
            pgrid = mc.sum_grids(grids, cols, rows_n)
            total_s = sum(v for r in pgrid for v in r)
            n = samples if samples is not None else (int(round(total_s * fps)) if fps else 0)
            db.add(PlayerHeatmap(stat_id=stat.stat_id, grid_cols=cols, grid_rows=rows_n, pitch_length_m=length,
                                 pitch_width_m=width, samples=n, cells=json.dumps(pgrid),
                                 source="pipeline", cell_unit="seconds"))
            used["heatmap"]["pipeline"] += 1
        elif mean is not None:
            db.add(PlayerHeatmap(stat_id=stat.stat_id, grid_cols=mc.GRID_COLS, grid_rows=mc.GRID_ROWS,
                                 pitch_length_m=length, pitch_width_m=width, samples=samples,
                                 cells=json.dumps(cells), source="backend", cell_unit="samples"))
            used["heatmap"]["backend"] += 1
        for key, val in vals.items():
            if key in mc.DEF_BY_KEY and mc.DEF_BY_KEY[key]["storage"] == "metric":
                metric_rows.append({"stat_id": stat.stat_id, "metric_key": key, "value": val})
    if metric_rows:
        db.execute(insert(PlayerMatchMetric), metric_rows)
    if out.heatmaps and used["heatmap"]["backend"]:
        out.adapter_warnings.append(f"heatmaps.json had no usable grid for {used['heatmap']['backend']} player(s); "
                                    "used backend heatmaps for them")
    out.adapter_metrics = {
        "sources": {k: dict(v) for k, v in used.items()},
        "speed_thresholds": speed_thresholds(meta),
        "heatmap_grid": ("pipeline" if used["heatmap"]["pipeline"] and not used["heatmap"]["backend"]
                         else "backend" if used["heatmap"]["backend"] and not used["heatmap"]["pipeline"]
                         else "mixed" if used["heatmap"]["pipeline"] else None),
    }


# --------------------------------------------------------------------------- ingest
def ingest_output(db: Session, video: MatchVideo, out: PipelineOutput) -> None:
    """Map tracks -> players, then replace this video's player_match_stats + tracking_detections."""
    match = db.get(Match, video.match_id)
    team_ids = {"home": match.home_team_id, "away": match.away_team_id}
    rosters: dict[str, dict[int, Player]] = {"home": {}, "away": {}}
    for side, tid in team_ids.items():
        for p in db.scalars(select(Player).where(Player.team_id == tid)).all():
            if p.jersey_number is not None:
                rosters[side][p.jersey_number] = p

    # per-track jersey / team / role: stats rows win, else majority vote over detections
    votes_j: dict[int, Counter] = defaultdict(Counter)
    votes_t: dict[int, Counter] = defaultdict(Counter)
    votes_r: dict[int, Counter] = defaultdict(Counter)
    for d in out.detections:
        tid = _opt_int(d.get("track_id"))
        if tid is None or tid < 0:
            continue
        if (j := _opt_int(d.get("jersey_number"))) is not None:
            votes_j[tid][j] += 1
        if (s := team_side(d.get("team"))) is not None:
            votes_t[tid][s] += 1
        if (r := _role(d)) is not None:
            votes_r[tid][r] += 1
    track_jersey = {t: c.most_common(1)[0][0] for t, c in votes_j.items()}
    track_side = {t: c.most_common(1)[0][0] for t, c in votes_t.items()}
    track_role = {t: c.most_common(1)[0][0] for t, c in votes_r.items()}
    for s in out.player_stats:
        tid = _opt_int(s.get("track_id"))
        if tid is None:
            continue
        if (j := _opt_int(s.get("jersey_number"))) is not None:
            track_jersey[tid] = j
        if (side := team_side(s.get("team"))) is not None:
            track_side[tid] = side
        if (r := _role(s)) is not None:
            track_role[tid] = r

    track_player: dict[int, Optional[int]] = {}

    def player_for(tid: int, create: bool) -> Optional[int]:
        if tid in track_player:
            return track_player[tid]
        if track_role.get(tid) in SKIP_ROLES:
            return None
        j, side = track_jersey.get(tid), track_side.get(tid)
        found = None
        if j is not None:
            if side:                          # team known: only that roster
                found = rosters[side].get(j)
            else:                             # unknown team: home roster first, then away
                found = rosters["home"].get(j) or rosters["away"].get(j)
        if found is not None:
            track_player[tid] = found.player_id
        elif create and settings.CV_CREATE_UNKNOWN_PLAYERS:
            team_id = team_ids[side or "home"]
            track_player[tid] = _placeholder_player(db, team_id, j, tid, video.video_id).player_id
        else:
            return None
        return track_player[tid]

    # ---- player_match_stats (one row per player per video; fragmented tracks merged) ----
    merged: dict[int, dict] = {}
    unknown_keys: set[str] = set()
    for s in out.player_stats:
        tid = _opt_int(s.get("track_id"))
        if tid is None or tid < 0 or _role(s) in SKIP_ROLES or track_role.get(tid) in SKIP_ROLES:
            continue
        pid = player_for(tid, create=True)
        if pid is None:
            continue
        risk = s.get("injury_risk") if s.get("injury_risk") in RISK_RANK else None
        m = merged.setdefault(pid, {"speed": None, "dist": None, "risk": None, "extra": {}, "tracks": []})
        m["tracks"].append(s)
        m["speed"] = _merge_max(m["speed"], _opt_float(s.get("top_speed_mph")))
        m["dist"] = _merge_sum(m["dist"], _opt_float(s.get("distance_km")))
        if risk:
            m["risk"] = max(m["risk"] or 0, RISK_RANK[risk])
        _collect_metrics(s, m["extra"], unknown_keys)

    # facts for the risk gates (risk_service.gate_match_row), kept in pipeline_meta.risk_gate
    placeholder_ids = set()
    for pid in merged:
        pl = db.get(Player, pid)
        if pl is not None and pl.first_name == "Unknown" and pl.position == "Unassigned":
            placeholder_ids.add(pid)
    out.risk_gate = {
        "placeholder_player_ids": sorted(placeholder_ids),
        "distance_invalid_player_ids": sorted(pid for pid, m in merged.items()
                                              if any(t.get("distance_valid") is False for t in m["tracks"])),
    }

    # metrics/heatmaps cascade from player_match_stats (FK ON DELETE CASCADE); delete explicitly too so this also
    # works on connections without FK enforcement
    old_ids = select(PlayerMatchStat.stat_id).where(PlayerMatchStat.video_id == video.video_id)
    db.execute(delete(PlayerMatchMetric).where(PlayerMatchMetric.stat_id.in_(old_ids)))
    db.execute(delete(PlayerHeatmap).where(PlayerHeatmap.stat_id.in_(old_ids)))
    db.execute(delete(PlayerMatchStat).where(PlayerMatchStat.video_id == video.video_id))
    stat_rows: dict[int, PlayerMatchStat] = {}
    for pid, m in merged.items():
        risk_label = RANK_RISK[m["risk"] or 1]
        mph = None if m["speed"] is None else round(min(m["speed"], 999.99), 2)
        km = None if m["dist"] is None else round(min(m["dist"], 999.999), 3)
        kmh_vals = [v for v in (_opt_float(t.get("top_speed_kmh")) for t in m["tracks"]) if v is not None]
        kmh = round(max(kmh_vals), 2) if kmh_vals else (None if mph is None else round(mph * MPH_TO_KMH, 2))
        meters = None if km is None else round(km * 1000.0, 2)
        spr_vals = [int(v) for v in (_opt_float(t.get("sprint_count")) for t in m["tracks"]) if v is not None]
        played_tracks = _track_minutes(m["tracks"], "minutes_played")  # minutes_played_s preferred; no fallback
        min_vals = [] if played_tracks is None else [played_tracks]
        ex = m.get("extra") or {}
        if not min_vals and _opt_float(ex.get("minutes_played")) is not None:
            min_vals = [_opt_float(ex.get("minutes_played"))]
        if not spr_vals and _opt_float(ex.get("sprint_count")) is not None:
            spr_vals = [int(_opt_float(ex.get("sprint_count")))]
        stat_rows[pid] = PlayerMatchStat(
            player_id=pid, match_id=match.match_id, video_id=video.video_id,
            top_speed_mph=None if mph is None else Decimal(str(mph)),
            distance_km=None if km is None else Decimal(str(km)),
            injury_risk=risk_label,
            top_speed_kmh=None if kmh is None else Decimal(str(min(kmh, 999.99))),
            distance_covered_meters=None if meters is None else Decimal(str(min(meters, 99999.99))),
            minutes_played=None if not min_vals else round(max(min_vals), 3),
            sprint_count=None if not spr_vals else int(sum(spr_vals)),
            fatigue_risk_score=_fatigue(risk_label),
        )
        db.add(stat_rows[pid])
    db.flush()
    if unknown_keys:
        out.adapter_warnings.append("Unknown per-player keys ignored (add a metric definition?): "
                                    + ", ".join(sorted(unknown_keys)))

    # ---- tracking_detections (replace this video's rows) ----
    db.execute(delete(TrackingDetection).where(TrackingDetection.video_id == video.video_id))
    rows = []
    for d in out.detections:
        tid = _opt_int(d.get("track_id"))
        frame = _opt_int(d.get("frame"))
        if tid is None or frame is None:
            continue
        role = _role(d) or track_role.get(tid)
        cls = str(role or d.get("class") or ("ball" if tid < 0 else "player"))[:20]
        x1 = _opt_float(d.get("bbox_x1")) or 0.0
        y1 = _opt_float(d.get("bbox_y1")) or 0.0
        x2 = _opt_float(d.get("bbox_x2")) or 0.0
        y2 = _opt_float(d.get("bbox_y2")) or 0.0
        xc, yc, bw, bh = _bbox_center_size(x1, y1, x2, y2)
        rows.append({
            "video_id": video.video_id,
            "player_id": player_for(tid, create=False) if tid >= 0 and role not in SKIP_ROLES else None,
            "track_id": tid, "frame_number": frame, "object_class": cls,
            "jersey_number": _opt_int(d.get("jersey_number")),
            "bbox_x1": x1, "bbox_y1": y1, "bbox_x2": x2, "bbox_y2": y2,
            "x_center": round(xc, 2), "y_center": round(yc, 2),
            "bbox_width": round(bw, 2), "bbox_height": round(bh, 2),
            "confidence": _opt_float(d.get("confidence")) or 0.0,
            "pitch_x": _opt_float(d.get("pitch_x")), "pitch_y": _opt_float(d.get("pitch_y")),
        })
    for i in range(0, len(rows), INSERT_CHUNK):
        db.execute(insert(TrackingDetection), rows[i:i + INSERT_CHUNK])

    # ---- extended metrics + heatmaps (player_match_metrics / player_heatmaps) ----
    _store_metrics(db, out, merged, stat_rows, rows)
    # Prefer metric-table values for minutes_played / sprint_count when the CV only put them there
    for pid, st in stat_rows.items():
        ex = (merged.get(pid) or {}).get("extra") or {}
        if st.minutes_played is None and _opt_float(ex.get("minutes_played")) is not None:
            st.minutes_played = round(_opt_float(ex.get("minutes_played")), 3)
        if st.sprint_count is None and _opt_float(ex.get("sprint_count")) is not None:
            st.sprint_count = int(_opt_float(ex.get("sprint_count")))

    # fps: meta.json if present, else estimate from the latest frame/timestamp pair
    meta = out.meta if isinstance(out.meta, dict) else {}
    meta_fps = _opt_float(meta.get("fps"))
    if meta_fps and meta_fps > 0:
        video.fps = round(meta_fps, 3)
    elif video.fps is None:
        best = max(((_opt_int(d.get("frame")) or 0, _opt_float(d.get("timestamp")) or 0.0)
                    for d in out.detections), default=(0, 0.0))
        if best[0] and best[1]:
            video.fps = round(best[0] / best[1], 2)
    res = _fmt_resolution(meta)
    if res:
        video.resolution = res
    dur = _opt_float(meta.get("duration_s"))
    if dur is not None and dur >= 0:
        video.duration_seconds = float(dur)


def _score_risk(db: Session, video_id: int) -> None:
    """Injury-risk scoring after ingest. Never fails the video: errors (no key, no model) are only logged."""
    try:
        import risk_service
        n = risk_service.rescore_video(db, video_id)
        db.commit()
        log.info("video %s: injury-risk scored %d row(s) (others gated: see player_match_risk.score_status)", video_id, n)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.warning("video %s: injury-risk scoring skipped: %s: %s", video_id, type(e).__name__, e)


def fail_interrupted_videos() -> int:
    """On startup: BackgroundTasks don't survive restarts, so mark leftovers failed."""
    db = SessionLocal()
    try:
        rows = db.scalars(select(MatchVideo).where(MatchVideo.processing_status.in_(["queued", "processing"]))).all()
        for v in rows:
            v.processing_status = "failed"
            v.stage = "failed"
            v.error_message = "Interrupted: server restarted before processing finished. Please re-upload."
            v.processed_at = utcnow()
        db.commit()
        return len(rows)
    finally:
        db.close()
