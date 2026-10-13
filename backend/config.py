"""Application settings, loaded from environment variables / backend/.env."""
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent
PLACEHOLDER_JWT_SECRET = "dev-only-placeholder-secret-change-me-in-dotenv-0000"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # BACKEND_ENV_FILE overrides the .env path; set it to "" to read no .env at all (the test suite does).
        env_file=(os.environ.get("BACKEND_ENV_FILE", str(BASE_DIR / ".env")) or None),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database / CORS ---
    DATABASE_URL: str = "mysql+pymysql://root:password@localhost:3306/soccer_analytics_app"
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    SQL_ECHO: bool = False

    # --- Auth (JWT) ---
    JWT_SECRET: str = PLACEHOLDER_JWT_SECRET
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    THUMBNAIL_TOKEN_EXPIRE_MINUTES: int = 60
    MEDIA_TOKEN_EXPIRE_MINUTES: int = 60      # source_url / frame_url / frames_url / annotated_url ?token= (re-fetch for a fresh one)

    # --- Uploads ---
    UPLOAD_DIR: Path = BASE_DIR / "uploads"
    MAX_UPLOAD_MB: int = 500
    ALLOWED_VIDEO_EXTENSIONS: str = "mp4,mov,avi,mkv"
    THUMBNAILS_ENABLED: bool = True           # ffmpeg (preferred) or cv2; never fails processing
    THUMBNAIL_DIR: Path = BASE_DIR / "uploads" / "thumbnails"

    # --- CV pipeline adapter (see pipeline.py) ---
    # Path to cv/run_pipeline.py from PR #1. Default: <repo root>/cv/run_pipeline.py
    CV_PIPELINE_PATH: Path = BASE_DIR.parent / "cv" / "run_pipeline.py"
    # Python interpreter that has the CV deps (ultralytics, torch, easyocr...).
    # Empty = same interpreter as the backend.
    CV_PYTHON: str = ""
    CV_DEVICE: str = "auto"                 # auto | cuda | mps | cpu
    CV_MODEL: str = ""                      # empty = pipeline default (yolov8x.pt)
    CV_CALIBRATION_PATH: Optional[Path] = None  # needed for speed/distance stats
    CV_EXTRA_ARGS: str = ""                 # e.g. "--no-ocr --ocr-sample-rate 5"
    CV_TIMEOUT_SECONDS: int = 4 * 60 * 60
    CV_OUTPUT_DIR: Path = BASE_DIR / "uploads" / "cv_outputs"
    # auto = real pipeline if CV_PIPELINE_PATH exists, else stub if CV_PIPELINE_STUB, else fail
    # real = always real, stub = always fake demo data
    CV_PIPELINE_MODE: str = "auto"
    # true = if the real pipeline isn't found, write fake demo stats instead of failing
    CV_PIPELINE_STUB: bool = False
    # true = tracks whose jersey number doesn't match a rostered player get a placeholder player
    CV_CREATE_UNKNOWN_PLAYERS: bool = True
    # Player tracking (tracking.py), independent of CV_PIPELINE_MODE:
    # auto = real if cv/track_player.py AND cv/detect_frame.py exist under the CV repo root, else stub
    # real = always cv.detect_frame / cv.track_player (fail clearly if missing), stub = always fake demo tracks
    TRACK_PIPELINE_MODE: str = "auto"
    CV_TRACK_TIMEOUT_SECONDS: int = 2 * 60 * 60
    CV_DETECT_TIMEOUT_SECONDS: int = 180

    # --- Health data / injury-risk model (v0.7.0) ---
    # AES-256-GCM key for heart rate + risk scores at rest: base64 of exactly 32 random bytes. Generate with
    #   python -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
    # Missing/malformed -> risk + CSV endpoints answer 503 and ingest skips scoring (logged at startup).
    HEALTH_DATA_KEY: str = ""
    RISK_RED_THRESHOLD: float = 70.0          # risk_percent >= this -> red
    RISK_YELLOW_THRESHOLD: float = 40.0       # >= this (and < red) -> yellow, else green
    RISK_MODEL_PATH: Path = BASE_DIR / "ml" / "risk_model.joblib"
    CSV_MAX_MB: int = 5                       # POST /api/uploads/csv size limit (MB)
    CSV_MAX_ROWS: int = 5000
    # false = skip the startup "mark interrupted videos/tracks failed" sweep. Set for a SECOND server process
    # (the HTTPS one on 8443) so starting it never fails jobs the HTTP process is still running.
    STARTUP_RECOVERY: bool = True

    @field_validator("CV_CALIBRATION_PATH", mode="before")
    @classmethod
    def _blank_is_none(cls, v):
        return None if v is None or (isinstance(v, str) and not v.strip()) else v

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def allowed_video_extensions(self) -> set[str]:
        return {e.strip().lower().lstrip(".") for e in self.ALLOWED_VIDEO_EXTENSIONS.split(",") if e.strip()}

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
