"""GET /api/config (public). (GET /api/matches moved to routers/matches.py.)"""
from fastapi import APIRouter

from config import settings
from schemas import PublicConfigOut

router = APIRouter(tags=["meta"])


@router.get("/api/config", response_model=PublicConfigOut)
def public_config() -> PublicConfigOut:
    """Upload limits for the frontend (no auth)."""
    return PublicConfigOut(max_upload_mb=settings.MAX_UPLOAD_MB,
                           allowed_extensions=sorted(settings.allowed_video_extensions))
