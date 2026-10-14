"""Optional JPEG thumbnail from ~1s into the video. ffmpeg preferred, cv2 fallback. Never raises."""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from config import settings

log = logging.getLogger("thumbnails")
WIDTH = 480


def _ffmpeg(video: Path, out: Path, seek: float) -> bool:
    exe = shutil.which("ffmpeg")
    if not exe:
        return False
    cmd = [exe, "-y", "-loglevel", "error", "-ss", str(seek), "-i", str(video),
           "-frames:v", "1", "-vf", f"scale={WIDTH}:-2", "-q:v", "4", str(out)]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.is_file() and out.stat().st_size > 0


def _cv2(video: Path, out: Path, seek: float) -> bool:
    try:
        import cv2  # optional: only if the backend venv happens to have opencv
    except Exception:
        return False
    cap = cv2.VideoCapture(str(video))
    try:
        if not cap.isOpened():
            return False
        cap.set(cv2.CAP_PROP_POS_MSEC, seek * 1000)
        ok, frame = cap.read()
        if not ok:
            cap.set(cv2.CAP_PROP_POS_MSEC, 0)
            ok, frame = cap.read()
        if not ok or frame is None:
            return False
        h, w = frame.shape[:2]
        frame = cv2.resize(frame, (WIDTH, max(2, int(h * WIDTH / w))))
        return bool(cv2.imwrite(str(out), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80]))
    finally:
        cap.release()


def make_thumbnail(video_path: Path, video_id: int) -> Optional[Path]:
    """Returns the JPEG path, or None if it couldn't be made (tools missing, unreadable video, ...)."""
    if not settings.THUMBNAILS_ENABLED:
        return None
    try:
        out_dir = Path(settings.THUMBNAIL_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{video_id}.jpg"
        out.unlink(missing_ok=True)
        for seek in (1.0, 0.0):  # clips shorter than 1s: fall back to the first frame
            if _ffmpeg(video_path, out, seek) or _cv2(video_path, out, seek):
                return out
        out.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001 - thumbnails are best-effort
        log.warning("thumbnail failed for video %s", video_id, exc_info=True)
    return None
