"""FastAPI entry point. Run from backend/:  uvicorn main:app --reload"""
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from config import PLACEHOLDER_JWT_SECRET, settings
from database import engine, get_db
from models import Player, Team, User
from pipeline import fail_interrupted_videos, resolve_mode
import metrics_catalog as mc
from database import SessionLocal
from routers import auth, insights, matches, meta, metrics, risk, tags, tracking, videos
from schemas import HealthOut, PlayerOut, PlayerPatchIn, PlayerStatMetricsOut, TeamBriefOut
from security import get_current_user
from stats import aggregate_player_stats, wants_metrics

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")
log = logging.getLogger("main")


def _risk_startup_check() -> None:
    """Log (never print) whether health-data encryption + the risk model are usable; warm the model."""
    import health_crypto
    ok, msg = health_crypto.key_status()
    (log.info if ok else log.error)("Health data: %s%s", msg,
                                    "" if ok else " -> /api/roster/risk and /api/uploads/csv will answer 503")
    try:
        from ml import scorer
        _, meta = scorer.load()
        log.info("Risk model: %s (%s)", meta["model_version"], settings.RISK_MODEL_PATH)
    except Exception as e:  # noqa: BLE001
        log.error("Risk model unavailable: %s", e)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.JWT_SECRET == PLACEHOLDER_JWT_SECRET:
        log.warning("JWT_SECRET is the placeholder value. Set a real one in backend/.env")
    log.info("CV pipeline mode: %s (CV_PIPELINE_PATH=%s)", resolve_mode(), settings.CV_PIPELINE_PATH)
    from tracking import track_mode
    log.info("Player tracking mode: %s (TRACK_PIPELINE_MODE=%s)", track_mode("track_player"), settings.TRACK_PIPELINE_MODE)
    _risk_startup_check()
    if not settings.STARTUP_RECOVERY:
        log.info("STARTUP_RECOVERY=false: skipping the interrupted video/track sweep (secondary server process)")
    try:
        n = fail_interrupted_videos() if settings.STARTUP_RECOVERY else 0
        if n:
            log.warning("Marked %d interrupted video(s) as failed", n)
    except Exception:  # DB down at startup is fine; /health will say so
        log.warning("Could not check for interrupted videos (database unreachable?)")
    try:
        from tracking import fail_interrupted_tracks
        n = fail_interrupted_tracks() if settings.STARTUP_RECOVERY else 0
        if n:
            log.warning("Marked %d interrupted tracking job(s) as failed", n)
    except Exception:  # noqa: BLE001
        log.warning("Could not check for interrupted tracking jobs (database unreachable?)")
    try:
        with SessionLocal() as db:
            n = mc.ensure_definitions(db)
            if n:
                log.info("metric_definitions: %d row(s) inserted/updated", n)
    except Exception:  # noqa: BLE001
        log.warning("Could not sync metric_definitions (database unreachable, or migration 004 not run?)")
    yield


app = FastAPI(title="Soccer Video Analytics API", version="0.7.0", lifespan=lifespan)

RISK_PATH_PREFIXES = ("/api/roster/risk", "/api/uploads/csv")


@app.middleware("http")
async def response_time(request: Request, call_next):
    """X-Response-Time-ms on every response (the risk dashboard's 3-second budget); log line for risk endpoints."""
    t0 = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - t0) * 1000.0
    response.headers["X-Response-Time-ms"] = f"{ms:.1f}"
    path = request.url.path
    if path.startswith(RISK_PATH_PREFIXES) or (path.startswith("/api/players/") and path.endswith("/risk")):
        log.info("latency %s %s -> %d in %.1f ms", request.method, path, response.status_code, ms)
    return response


@app.middleware("http")
async def json_500(request: Request, call_next):
    """Unhandled errors -> 500 {"detail": "Internal server error"} (JSON, like every other error). Registered
    before CORSMiddleware so CORS stays the outer layer and the browser can read the body."""
    try:
        return await call_next(request)
    except OperationalError:
        return JSONResponse(status_code=503, content={"detail": "Database unavailable"})
    except Exception:  # noqa: BLE001
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
    expose_headers=["X-Response-Time-ms"],
)


@app.exception_handler(OperationalError)
async def db_unavailable_handler(request: Request, exc: OperationalError) -> JSONResponse:
    """Return a clean 503 (with CORS headers) instead of a raw 500 when MySQL is down."""
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.get("/health", response_model=HealthOut, tags=["meta"])
def health() -> HealthOut:
    """Liveness check. Never 500s: reports db='unreachable' if the DB is down."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "unreachable"
    return HealthOut(status="ok", db=db_status)


app.include_router(auth.router)
app.include_router(videos.router)
app.include_router(meta.router)
app.include_router(matches.router)
app.include_router(tags.router)
app.include_router(metrics.router)
app.include_router(insights.router)
app.include_router(tracking.router)
app.include_router(risk.router)


def _player_out(p: Player, team: Team) -> PlayerOut:
    return PlayerOut(
        player_id=p.player_id, team_id=p.team_id, first_name=p.first_name, last_name=p.last_name,
        jersey_number=p.jersey_number, position=p.position, dominant_foot=p.dominant_foot,
        contract_end_date=p.contract_end_date, created_at=p.created_at,
        team=TeamBriefOut(team_id=team.team_id, team_name=team.team_name, league=team.league,
                          created_at=team.created_at),
    )


def _owned_player(db: Session, user: User, player_id: int) -> tuple[Player, Team]:
    row = db.execute(
        select(Player, Team).join(Team, Team.team_id == Player.team_id)
        .where(Player.player_id == player_id, Team.user_id == user.user_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Player not found")
    return row[0], row[1]


# NOTE: /api/players/stats and /api/players (list) MUST be declared before /api/players/{player_id}.
@app.get("/api/players/stats", response_model=list[PlayerStatMetricsOut], response_model_exclude_unset=True,
         tags=["players"])
def player_stats(
    match_id: Optional[int] = Query(None, description="Only include stats from this match"),
    team_id: Optional[int] = Query(None, description="Only include players on this team"),
    include: Optional[str] = Query(None, description="'metrics' adds metrics {key: value|null} + avg_position"),
    metrics: Optional[str] = Query(None, description="Comma-separated metric keys (default: all)"),
    db: Session = Depends(get_db),
):
    """Per-player aggregate across player_match_stats:
    max top speed, total distance, worst injury risk. Players with no stats are excluded.
    Unchanged shape unless ?include=metrics (then ERD names are included too)."""
    return aggregate_player_stats(db, match_id=match_id, team_id=team_id,
                                  include_metrics=wants_metrics(include), metric_keys=mc.parse_keys(metrics),
                                  flat=wants_metrics(include))


@app.get("/api/players", response_model=list[PlayerOut], tags=["players"])
def list_players(
    team_id: Optional[int] = Query(None, description="Only players on this team (must be yours)"),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> list[PlayerOut]:
    """Players page: all of your players, or one team. Each row includes a nested `team`."""
    if team_id is not None:
        team = db.scalar(select(Team).where(Team.team_id == team_id, Team.user_id == user.user_id))
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")
        rows = db.execute(
            select(Player, Team).join(Team, Team.team_id == Player.team_id)
            .where(Player.team_id == team_id).order_by(Player.player_id)
        ).all()
    else:
        rows = db.execute(
            select(Player, Team).join(Team, Team.team_id == Player.team_id)
            .where(Team.user_id == user.user_id).order_by(Player.player_id)
        ).all()
    return [_player_out(p, t) for p, t in rows]


@app.get("/api/players/{player_id}", response_model=PlayerOut, tags=["players"])
def get_player(player_id: int, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)) -> PlayerOut:
    return _player_out(*_owned_player(db, user, player_id))


@app.patch("/api/players/{player_id}", response_model=PlayerOut, tags=["players"])
def patch_player(player_id: int, body: PlayerPatchIn,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> PlayerOut:
    """Partial update for the Players page. JSON null clears jersey_number / position / dominant_foot /
    contract_end_date. 409 if the jersey is already taken on the same team."""
    p, team = _owned_player(db, user, player_id)
    data = body.model_dump(exclude_unset=True)
    if "jersey_number" in data and data["jersey_number"] is not None:
        clash = db.scalar(
            select(Player).where(Player.team_id == p.team_id, Player.jersey_number == data["jersey_number"],
                                 Player.player_id != p.player_id)
        )
        if clash is not None:
            raise HTTPException(status_code=409,
                                detail=f"Jersey number {data['jersey_number']} is already taken on this team")
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    db.refresh(team)
    return _player_out(p, team)
