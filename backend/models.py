"""SQLAlchemy 2.x ORM models. Keep in sync with schema.sql."""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from timeutil import utcnow

INJURY_RISK_VALUES = ("Low", "Medium", "High")
PROCESSING_STATUS_VALUES = ("queued", "processing", "done", "failed")

# BIGINT in MySQL; plain INTEGER on SQLite so autoincrement still works in tests.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    first_name: Mapped[str] = mapped_column(String(50))
    last_name: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="analyst", server_default="analyst")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, server_default=func.current_timestamp())  # UTC

    teams: Mapped[list["Team"]] = relationship(back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    videos: Mapped[list["MatchVideo"]] = relationship(back_populates="user", cascade="all, delete-orphan", passive_deletes=True)


class Team(Base):
    __tablename__ = "teams"

    team_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    team_name: Mapped[str] = mapped_column(String(100))
    league: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=utcnow, server_default=func.current_timestamp())

    user: Mapped["User"] = relationship(back_populates="teams")
    players: Mapped[list["Player"]] = relationship(back_populates="team", cascade="all, delete-orphan", passive_deletes=True)


class Player(Base):
    __tablename__ = "players"
    __table_args__ = (UniqueConstraint("team_id", "jersey_number", name="uq_players_team_jersey"),)

    player_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.team_id", ondelete="CASCADE"), index=True)
    first_name: Mapped[str] = mapped_column(String(50))
    last_name: Mapped[str] = mapped_column(String(50))
    jersey_number: Mapped[Optional[int]] = mapped_column(Integer)
    position: Mapped[Optional[str]] = mapped_column(String(30))
    dominant_foot: Mapped[Optional[str]] = mapped_column(Enum("Left", "Right", "Both", name="dominant_foot"))
    contract_end_date: Mapped[Optional[date]] = mapped_column(Date)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=utcnow, server_default=func.current_timestamp())

    team: Mapped["Team"] = relationship(back_populates="players")
    stats: Mapped[list["PlayerMatchStat"]] = relationship(back_populates="player", cascade="all, delete-orphan", passive_deletes=True)


class Match(Base):
    __tablename__ = "matches"

    match_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.team_id", ondelete="CASCADE"), index=True)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.team_id", ondelete="CASCADE"), index=True)
    match_date: Mapped[date] = mapped_column(Date)
    stadium_name: Mapped[Optional[str]] = mapped_column(String(100))
    weather_condition: Mapped[Optional[str]] = mapped_column(String(50))
    tactical_formation: Mapped[Optional[str]] = mapped_column(String(20))
    # Result (migration 005). Scores are nullable (unknown). `our_side` says which team is "ours" when the user owns
    # both teams (default home); `result` (W/D/L from our side) is derived from the scores when both are set,
    # otherwise it can be set by hand.
    home_score: Mapped[Optional[int]] = mapped_column(Integer)
    away_score: Mapped[Optional[int]] = mapped_column(Integer)
    our_side: Mapped[Optional[str]] = mapped_column(Enum("home", "away", name="our_side"))
    result: Mapped[Optional[str]] = mapped_column(Enum("W", "D", "L", name="match_result"))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=utcnow, server_default=func.current_timestamp())

    home_team: Mapped["Team"] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped["Team"] = relationship(foreign_keys=[away_team_id])
    videos: Mapped[list["MatchVideo"]] = relationship(back_populates="match", cascade="all, delete-orphan", passive_deletes=True)
    tags: Mapped[list["MatchTag"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class MatchVideo(Base):
    __tablename__ = "match_videos"

    video_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.match_id", ondelete="CASCADE"), index=True)
    # Nullable so rows created before migration 001 stay valid; the API always sets it.
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    title: Mapped[Optional[str]] = mapped_column(String(255))
    file_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(500))
    video_type: Mapped[str] = mapped_column(
        Enum("tactical_cam", "broadcast", "endzone_cam", name="video_type"),
        default="tactical_cam", server_default="tactical_cam",
    )
    fps: Mapped[Optional[float]] = mapped_column(Float)
    resolution: Mapped[Optional[str]] = mapped_column(String(20))
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float)
    processing_status: Mapped[str] = mapped_column(
        Enum(*PROCESSING_STATUS_VALUES, name="processing_status"), default="queued", server_default="queued"
    )
    # Coarse progress for the UI: queued|detect|track|ocr|metrics|ingest|done|failed, 0-100
    stage: Mapped[str] = mapped_column(String(20), default="queued", server_default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(500))
    # JSON text: CV meta.json (fps, pipeline_version, warnings, ...) + adapter info (adapter_source real|stub)
    pipeline_meta: Mapped[Optional[str]] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, server_default=func.current_timestamp())  # UTC
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # UTC

    match: Mapped["Match"] = relationship(back_populates="videos")
    user: Mapped[Optional["User"]] = relationship(back_populates="videos")


class PlayerMatchStat(Base):
    """One row per player per processed video (video_id NULL = legacy/manual row not tied to a video)."""
    __tablename__ = "player_match_stats"
    __table_args__ = (UniqueConstraint("player_id", "video_id", name="uq_stats_player_video"),)

    stat_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.player_id", ondelete="CASCADE"), index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.match_id", ondelete="CASCADE"), index=True)
    video_id: Mapped[Optional[int]] = mapped_column(ForeignKey("match_videos.video_id", ondelete="CASCADE"), index=True)
    # NULL when the pipeline ran without calibration
    top_speed_mph: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    distance_km: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 3))
    injury_risk: Mapped[str] = mapped_column(Enum(*INJURY_RISK_VALUES, name="injury_risk"), default="Low", server_default="Low")
    # ERD names (v0.6.0); filled at ingest alongside mph/km/injury_risk
    distance_covered_meters: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 2))
    top_speed_kmh: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    minutes_played: Mapped[Optional[float]] = mapped_column(Float)
    sprint_count: Mapped[Optional[int]] = mapped_column(Integer)
    fatigue_risk_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))

    player: Mapped["Player"] = relationship(back_populates="stats")


class TrackingDetection(Base):
    __tablename__ = "tracking_detections"
    __table_args__ = (Index("idx_detections_video_frame", "video_id", "frame_number"),)

    detection_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("match_videos.video_id", ondelete="CASCADE"))
    player_id: Mapped[Optional[int]] = mapped_column(ForeignKey("players.player_id", ondelete="SET NULL"), index=True)
    track_id: Mapped[int] = mapped_column(Integer)
    frame_number: Mapped[int] = mapped_column(Integer)
    object_class: Mapped[str] = mapped_column(String(20), default="player", server_default="player")  # player | ball
    jersey_number: Mapped[Optional[int]] = mapped_column(Integer)  # OCR result from the CV pipeline
    bbox_x1: Mapped[float] = mapped_column(Float)
    bbox_y1: Mapped[float] = mapped_column(Float)
    bbox_x2: Mapped[float] = mapped_column(Float)
    bbox_y2: Mapped[float] = mapped_column(Float)
    x_center: Mapped[Optional[float]] = mapped_column(Float)
    y_center: Mapped[Optional[float]] = mapped_column(Float)
    bbox_width: Mapped[Optional[float]] = mapped_column(Float)
    bbox_height: Mapped[Optional[float]] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    pitch_x: Mapped[Optional[float]] = mapped_column(Float)
    pitch_y: Mapped[Optional[float]] = mapped_column(Float)


# --------------------------------------------------------------------------- metrics (migration 004)
class MetricDefinition(Base):
    """Registry of per-player metrics (seeded from metrics_catalog.DEFINITIONS). storage='column' = lives on
    player_match_stats (distance_km, top_speed_mph); storage='metric' = rows in player_match_metrics."""
    __tablename__ = "metric_definitions"

    metric_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(100))
    unit: Mapped[Optional[str]] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(30))
    value_type: Mapped[str] = mapped_column(String(10), default="float", server_default="float")
    aggregation: Mapped[str] = mapped_column(String(10))  # sum | max | min | avg | ratio
    ratio_numerator: Mapped[Optional[str]] = mapped_column(String(64))
    ratio_denominator: Mapped[Optional[str]] = mapped_column(String(64))
    ratio_scale: Mapped[float] = mapped_column(Float, default=1.0, server_default="1")
    decimals: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    higher_is_better: Mapped[Optional[bool]] = mapped_column(Boolean)
    requires_calibration: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    is_estimate: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    availability: Mapped[str] = mapped_column(String(10), default="ready", server_default="ready")  # ready | soon
    storage: Mapped[str] = mapped_column(String(10), default="metric", server_default="metric")    # column | metric
    description: Mapped[Optional[str]] = mapped_column(String(500))
    sort_order: Mapped[int] = mapped_column(Integer, default=100, server_default="100")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")


class PlayerMatchMetric(Base):
    """Key-value metric per player_match_stats row (i.e. per player per video). value NULL = not available."""
    __tablename__ = "player_match_metrics"
    __table_args__ = (Index("ix_pmm_metric_value", "metric_key", "value"),)

    stat_id: Mapped[int] = mapped_column(ForeignKey("player_match_stats.stat_id", ondelete="CASCADE"), primary_key=True)
    metric_key: Mapped[str] = mapped_column(
        ForeignKey("metric_definitions.metric_key", ondelete="CASCADE", onupdate="CASCADE"), primary_key=True)
    value: Mapped[Optional[float]] = mapped_column(Float)


class PlayerHeatmap(Base):
    """Coarse occupancy grid per player per video from tracking_detections pitch_x/pitch_y.
    cells = JSON [[value,...cols] ...rows]; row 0 = pitch_y 0, col 0 = pitch_x 0. source=pipeline: heatmaps.json
    (21x14, seconds); source=backend: computed from tracking_detections (12x8, sample counts)."""
    __tablename__ = "player_heatmaps"

    stat_id: Mapped[int] = mapped_column(ForeignKey("player_match_stats.stat_id", ondelete="CASCADE"), primary_key=True)
    grid_cols: Mapped[int] = mapped_column(Integer)
    grid_rows: Mapped[int] = mapped_column(Integer)
    pitch_length_m: Mapped[float] = mapped_column(Float)
    pitch_width_m: Mapped[float] = mapped_column(Float)
    samples: Mapped[int] = mapped_column(Integer)
    cells: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10), default="backend", server_default="backend")   # pipeline|backend
    cell_unit: Mapped[str] = mapped_column(String(10), default="samples", server_default="samples")  # seconds|samples


class VideoPlayerOverride(Base):
    """Per-video corrections for a player as detected in ONE video (migration 007). jersey_number here overrides
    players.jersey_number in that video's stats only (NULL = "no number" in this video). Keyed per video, not on
    the players row, so it stays correct when the CV pipeline's player_uid keying (PR #2) lands: an assignment
    belongs to what was seen in that clip, and the roster's own number is never rewritten."""
    __tablename__ = "video_player_overrides"

    video_id: Mapped[int] = mapped_column(ForeignKey("match_videos.video_id", ondelete="CASCADE"), primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.player_id", ondelete="CASCADE"), primary_key=True,
                                           index=True)
    jersey_number: Mapped[Optional[int]] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow,
                                                 server_default=func.current_timestamp())  # UTC


TRACK_STATUS_VALUES = ("queued", "processing", "done", "failed")


class PlayerTrack(Base):
    """One "follow this player through the clip" track (migration 008). Target (target_mode):
    'bbox' = a box on one frame (init_frame + bbox_*), 'player' = an app player_id (resolved to a stored detection),
    'jersey' = a shirt number (team optional). bbox_* are NORMALISED 0-1 [x, y, w, h], top-left origin.
    fps/frame_count/width/height = source video geometry (known at creation). Files live in
    CV_OUTPUT_DIR/track_<track_id>/ (frames_api.json, annotated.mp4, raw CV files)."""
    __tablename__ = "player_tracks"
    __table_args__ = (Index("ix_player_tracks_video_status", "video_id", "status"),)

    track_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("match_videos.video_id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    target_mode: Mapped[str] = mapped_column(String(10))  # bbox | player | jersey
    init_frame: Mapped[Optional[int]] = mapped_column(Integer)
    init_t: Mapped[Optional[float]] = mapped_column(Float)
    bbox_x: Mapped[Optional[float]] = mapped_column(Float)
    bbox_y: Mapped[Optional[float]] = mapped_column(Float)
    bbox_w: Mapped[Optional[float]] = mapped_column(Float)
    bbox_h: Mapped[Optional[float]] = mapped_column(Float)
    player_id: Mapped[Optional[int]] = mapped_column(ForeignKey("players.player_id", ondelete="SET NULL"), index=True)
    jersey_number: Mapped[Optional[int]] = mapped_column(Integer)
    team: Mapped[Optional[str]] = mapped_column(String(1))  # A | B (CV pipeline team labels)
    fps: Mapped[Optional[float]] = mapped_column(Float)
    frame_count: Mapped[Optional[int]] = mapped_column(Integer)
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Enum(*TRACK_STATUS_VALUES, name="player_track_status"),
                                        default="queued", server_default="queued")
    stage: Mapped[str] = mapped_column(String(20), default="queued", server_default="queued")  # queued|detect|tracking|rendering|done|failed
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    output_dir: Mapped[Optional[str]] = mapped_column(String(500))
    frames_path: Mapped[Optional[str]] = mapped_column(String(500))
    annotated_path: Mapped[Optional[str]] = mapped_column(String(500))
    meta: Mapped[Optional[str]] = mapped_column(Text)   # JSON: CV meta.json + track summary + adapter info
    stats: Mapped[Optional[str]] = mapped_column(Text)  # JSON: target_stats.json (player_match_stats-shaped) or NULL
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, server_default=func.current_timestamp())  # UTC
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow,
                                                 server_default=func.current_timestamp())  # UTC
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # UTC


# --------------------------------------------------------------------------- tags (migration 005)
class TagKey(Base):
    __tablename__ = "tag_keys"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_tag_keys_user_name"),)

    tag_key_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, server_default=func.current_timestamp())

    values: Mapped[list["TagValue"]] = relationship(back_populates="key", cascade="all, delete-orphan",
                                                    passive_deletes=True)


class TagValue(Base):
    __tablename__ = "tag_values"
    __table_args__ = (UniqueConstraint("tag_key_id", "value", name="uq_tag_values_key_value"),)

    tag_value_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tag_key_id: Mapped[int] = mapped_column(ForeignKey("tag_keys.tag_key_id", ondelete="CASCADE"), index=True)
    value: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, server_default=func.current_timestamp())

    key: Mapped["TagKey"] = relationship(back_populates="values")


class MatchTag(Base):
    """Tags live on the MATCH (insights are per match); tagging a video tags its match."""
    __tablename__ = "match_tags"

    match_id: Mapped[int] = mapped_column(ForeignKey("matches.match_id", ondelete="CASCADE"), primary_key=True)
    tag_value_id: Mapped[int] = mapped_column(ForeignKey("tag_values.tag_value_id", ondelete="CASCADE"),
                                              primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, server_default=func.current_timestamp())

    tag_value: Mapped["TagValue"] = relationship()


# --------------------------------------------------------------------------- injury-risk model (migration 010)
class CsvUpload(Base):
    """One POST /api/uploads/csv (athlete logs). Deleting it deletes its logs (and their risk rows)."""
    __tablename__ = "csv_uploads"

    upload_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.team_id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(255))
    rows_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rows_valid: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rows_invalid: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rows_unmatched: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, server_default=func.current_timestamp())  # UTC


class AthleteLog(Base):
    """One CSV athlete-log row matched to a player. heart_rate*_enc = AES-256-GCM (health_crypto), never plaintext."""
    __tablename__ = "athlete_logs"
    __table_args__ = (Index("ix_athlete_logs_player_date", "player_id", "log_date"),)

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("csv_uploads.upload_id", ondelete="CASCADE"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.player_id", ondelete="CASCADE"))
    log_date: Mapped[date] = mapped_column(Date)
    source_row: Mapped[int] = mapped_column(Integer)  # 1-based CSV line (header = 1)
    gps_distance_km: Mapped[Optional[float]] = mapped_column(Float)
    minutes_played: Mapped[Optional[float]] = mapped_column(Float)
    sprints: Mapped[Optional[int]] = mapped_column(Integer)
    top_speed_kmh: Mapped[Optional[float]] = mapped_column(Float)
    heart_rate_enc: Mapped[Optional[str]] = mapped_column(Text)
    heart_rate_max_enc: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, server_default=func.current_timestamp())  # UTC


class PlayerMatchRisk(Base):
    """One risk evaluation per player_match_stats row (source 'match') or athlete_logs row (source 'csv').
    risk_percent_enc / details_enc = AES-256-GCM. Gated-out rows keep risk_percent_enc NULL, level 'unknown'."""
    __tablename__ = "player_match_risk"
    __table_args__ = (Index("ix_pmr_player_date", "player_id", "score_date"),)

    risk_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.player_id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(10))  # match | csv
    stat_id: Mapped[Optional[int]] = mapped_column(ForeignKey("player_match_stats.stat_id", ondelete="CASCADE"), unique=True)
    log_id: Mapped[Optional[int]] = mapped_column(ForeignKey("athlete_logs.log_id", ondelete="CASCADE"), unique=True)
    match_id: Mapped[Optional[int]] = mapped_column(ForeignKey("matches.match_id", ondelete="CASCADE"), index=True)
    video_id: Mapped[Optional[int]] = mapped_column(ForeignKey("match_videos.video_id", ondelete="CASCADE"), index=True)
    score_date: Mapped[Optional[date]] = mapped_column(Date)  # match_date or log_date
    risk_percent_enc: Mapped[Optional[str]] = mapped_column(Text)
    level: Mapped[str] = mapped_column(String(10), default="unknown", server_default="unknown")
    score_status: Mapped[str] = mapped_column(String(20), default="scored", server_default="scored")
    score_note: Mapped[Optional[str]] = mapped_column(String(255))
    data_quality: Mapped[Optional[str]] = mapped_column(String(12))  # calibrated | csv | demo | NULL
    model_version: Mapped[str] = mapped_column(String(40))
    details_enc: Mapped[Optional[str]] = mapped_column(Text)  # JSON: display features, model features, contributions
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, server_default=func.current_timestamp())  # UTC
