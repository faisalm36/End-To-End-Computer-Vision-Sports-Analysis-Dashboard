"""Pydantic request/response models."""
import math
from datetime import date, datetime
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import (BaseModel, ConfigDict, EmailStr, Field, PlainSerializer, StrictInt, field_validator,
                      model_validator)

from timeutil import iso_utc

InjuryRisk = Literal["Low", "Medium", "High"]
VideoStatus = Literal["queued", "processing", "done", "failed"]

# Stored as naive UTC; always serialized as ISO 8601 with "Z" (e.g. "2026-09-30T21:20:19Z").
UTCDateTime = Annotated[datetime, PlainSerializer(iso_utc, return_type=Optional[str], when_used="always")]


class HealthOut(BaseModel):
    status: str
    db: Literal["ok", "unreachable"]


# ---------- players ----------
class PlayerStatOut(BaseModel):
    """Shape consumed by frontend/src/Dashboard.jsx. Speed/distance are null when uncalibrated (key always present).
    v0.6.0 also carries ERD names (metres / kmh / fatigue) when the flat/metrics shape is used; the bare
    /api/players/stats list keeps the five classic fields unless ?include=metrics."""
    player_id: int
    name: str
    top_speed_mph: Optional[float]
    distance_km: Optional[float]
    injury_risk: InjuryRisk


class PlayerStatMetricsOut(PlayerStatOut):
    """PlayerStatOut + (only with ?include=metrics) `metrics` {key: value|null} and `avg_position` {x,y}|null.
    Endpoints use response_model_exclude_unset so the plain shape is unchanged without include=metrics."""
    metrics: Optional[dict[str, Optional[Union[int, float]]]] = None  # int for count metrics
    avg_position: Optional[dict[str, float]] = None
    # flat extras (frontend contract): always on /api/videos/{id}/stats, on /api/players/stats with include=metrics
    jersey_number: Optional[int] = None
    top_speed_kmh: Optional[float] = None
    distance_covered_meters: Optional[float] = None
    fatigue_risk_score: Optional[float] = None
    minutes_played: Optional[float] = None
    visible_minutes: Optional[float] = None
    coverage_pct: Optional[float] = None
    distance_per_min: Optional[float] = None
    hsr_distance_km: Optional[float] = None
    sprint_distance_km: Optional[float] = None
    hsr_count: Optional[int] = None
    sprint_count: Optional[int] = None
    high_intensity_efforts: Optional[int] = None
    accels: Optional[int] = None
    decels: Optional[int] = None
    speed_zones: Optional[dict[str, Optional[float]]] = None   # {walk, jog, run, hsr, sprint} km, null if unknown
    heatmap: Optional[dict[str, Any]] = None                    # {cols, rows, cells: row-major 0-1, samples}
    # video stats only: {preset, hsr_kmh, sprint_kmh, zone_edges_kmh, source}; source "default" = meta.json had none
    speed_thresholds: Optional[dict[str, Any]] = None


class VideoPlayerPatchIn(BaseModel):
    """PATCH /api/videos/{id}/players/{player_id}. jersey_number is required: an int 0-99, or null (= no number)."""
    model_config = ConfigDict(extra="forbid")

    jersey_number: Optional[Annotated[StrictInt, Field(ge=0, le=99)]] = Field(
        ..., description="Required. Integer 0-99, or null = no number in this video")


class TeamBriefOut(BaseModel):
    """Nested team on player responses (Players page)."""
    model_config = ConfigDict(from_attributes=True)

    team_id: int
    team_name: str
    league: Optional[str] = None
    created_at: Optional[UTCDateTime] = None


class PlayerOut(BaseModel):
    """GET/PATCH /api/players/{id} and GET /api/players list item (v0.6.0 enriched)."""
    model_config = ConfigDict(from_attributes=True)

    player_id: int
    team_id: int
    first_name: str
    last_name: str
    jersey_number: Optional[int] = None
    position: Optional[str] = None
    dominant_foot: Optional[str] = None
    contract_end_date: Optional[date] = None
    created_at: Optional[UTCDateTime] = None
    team: Optional[TeamBriefOut] = None


class PlayerPatchIn(BaseModel):
    """PATCH /api/players/{id}. All optional; omit = leave; JSON null clears a nullable field."""
    model_config = ConfigDict(extra="forbid")

    first_name: Optional[str] = Field(None, min_length=1, max_length=50)
    last_name: Optional[str] = Field(None, max_length=50)
    jersey_number: Optional[Annotated[StrictInt, Field(ge=0, le=99)]] = None
    position: Optional[str] = Field(None, max_length=30)
    dominant_foot: Optional[Literal["Left", "Right", "Both"]] = None
    contract_end_date: Optional[date] = None

    @model_validator(mode="after")
    def _at_least_one(self):
        # Distinguish "omitted" from "explicit null" via model_fields_set
        if not self.model_fields_set:
            raise ValueError("provide at least one field to update")
        if "first_name" in self.model_fields_set:
            if self.first_name is None:
                raise ValueError("first_name cannot be cleared")
            self.first_name = self.first_name.strip()
            if not self.first_name:
                raise ValueError("first_name cannot be blank")
        if "last_name" in self.model_fields_set and self.last_name is not None:
            self.last_name = self.last_name.strip()
        if "position" in self.model_fields_set and self.position is not None:
            self.position = self.position.strip() or None
        return self


# ---------- auth ----------
def _check_password(v: str) -> str:
    if len(v.encode("utf-8")) > 72:
        raise ValueError("password must be at most 72 bytes (bcrypt limit)")
    return v


def split_name(name: str) -> tuple[str, str]:
    """'Faisal Musa Jr' -> ('Faisal', 'Musa Jr'); 'Faisal' -> ('Faisal', '')."""
    parts = name.strip().split(" ", 1)
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")


class RegisterIn(BaseModel):
    """Either `name` ("First Last", split on the first space) or first_name + last_name."""
    first_name: Optional[str] = Field(None, min_length=1, max_length=50)
    last_name: Optional[str] = Field(None, min_length=1, max_length=50)
    name: Optional[str] = Field(None, min_length=1, max_length=101)
    email: EmailStr
    password: str = Field(min_length=8)

    _pw = field_validator("password")(classmethod(lambda cls, v: _check_password(v)))

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str) -> str:
        return v.lower()

    @model_validator(mode="after")
    def names(self):
        if self.first_name is None and self.last_name is None and self.name:
            self.first_name, self.last_name = split_name(self.name)
        if not (self.first_name and self.first_name.strip()):
            raise ValueError("provide `name` or `first_name` (+ `last_name`)")
        if len(self.first_name) > 50 or len(self.last_name or "") > 50:
            raise ValueError("first_name/last_name must be at most 50 characters")
        self.last_name = (self.last_name or "").strip()
        return self


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int  # seconds


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int          # same as user_id (the frontend reads `id`)
    user_id: int
    name: str
    first_name: str
    last_name: str
    email: str
    role: str
    created_at: Optional[UTCDateTime] = None

    @classmethod
    def of(cls, u) -> "UserOut":
        return cls(id=u.user_id, user_id=u.user_id, name=f"{u.first_name} {u.last_name}".strip(), first_name=u.first_name,
                   last_name=u.last_name, email=u.email, role=u.role, created_at=u.created_at)


class AuthOut(TokenOut):
    """Login response: the token plus the user (so the frontend needs no extra /me call)."""
    user: UserOut


class RegisterOut(UserOut):
    """Register response. Top level = the user object (unchanged, backward compatible) plus an access token
    and a nested `user` copy, so the frontend can log in straight away."""
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserOut


class UpdateMeIn(BaseModel):
    """`name` is split on the first space; explicit first_name/last_name override it."""
    name: Optional[str] = Field(None, min_length=1, max_length=101)
    first_name: Optional[str] = Field(None, min_length=1, max_length=50)
    last_name: Optional[str] = Field(None, max_length=50)

    @model_validator(mode="after")
    def not_empty(self):
        if self.name is None and self.first_name is None and self.last_name is None:
            raise ValueError("provide name and/or first_name/last_name")
        return self


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)

    _pw = field_validator("new_password")(classmethod(lambda cls, v: _check_password(v)))


# ---------- config / matches ----------
class PublicConfigOut(BaseModel):
    max_upload_mb: int
    allowed_extensions: list[str]


class TagIn(BaseModel):
    key: str = Field(min_length=1, max_length=50)
    value: str = Field(min_length=1, max_length=100)


class TagOut(BaseModel):
    key: str
    value: str


class TagsIn(BaseModel):
    tags: list[TagIn] = Field(max_length=50)


class MatchOut(BaseModel):
    match_id: int
    match_date: date
    home_team: str
    away_team: str
    home_team_id: int
    away_team_id: int
    video_count: int
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    our_side: Literal["home", "away"]          # effective side of "your" team
    our_team: str
    opponent: str
    result: Optional[Literal["W", "D", "L"]] = None   # from our_side's perspective
    created_at: Optional[UTCDateTime] = None
    tags: list[TagOut] = []


class MatchPatchIn(BaseModel):
    """All optional. Scores must be given as a pair (or both null). `result` may only be set by hand when there
    are no scores; with scores it is derived (a contradicting result -> 422)."""
    home_score: Optional[int] = Field(None, ge=0, le=99)
    away_score: Optional[int] = Field(None, ge=0, le=99)
    our_side: Optional[Literal["home", "away"]] = None
    result: Optional[Literal["W", "D", "L"]] = None


# ---------- videos ----------
class MatchSummary(BaseModel):
    match_id: int
    match_date: date
    home_team: str
    away_team: str
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    result: Optional[Literal["W", "D", "L"]] = None


VideoStage = Literal["queued", "detect", "track", "ocr", "metrics", "ingest", "done", "failed"]


class VideoOut(BaseModel):
    """List item / upload response. `id` and `video_id` are the same value (alias kept)."""
    id: int
    video_id: int
    match_id: int
    title: Optional[str] = None
    file_name: str
    match_date: Optional[date] = None
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    status: VideoStatus
    stage: VideoStage
    progress: int
    error_message: Optional[str] = None
    error: Optional[str] = None              # alias of error_message (the frontend reads `error`)
    created_at: Optional[UTCDateTime] = None
    uploaded_at: Optional[UTCDateTime] = None   # same as created_at (kept for compatibility)
    processed_at: Optional[UTCDateTime] = None
    fps: Optional[float] = None
    video_type: Optional[Literal["tactical_cam", "broadcast", "endzone_cam"]] = "tactical_cam"
    resolution: Optional[str] = None
    duration_seconds: Optional[float] = None
    thumbnail_url: Optional[str] = None      # relative URL incl. a short-lived ?token=; prefix with API base
    source_url: Optional[str] = None         # original upload: GET /api/videos/{id}/source?token= (Range); null if the file is gone
    match: Optional[MatchSummary] = None     # kept for compatibility
    result: Optional[Literal["W", "D", "L"]] = None   # = match.result (our side's view)
    tags: list[TagOut] = []                  # the match's tags (tags live on the match)


class VideoDetailOut(VideoOut):
    pipeline_meta: Optional[dict[str, Any]] = None  # raw meta.json + adapter_* info


# ---------- player tracking ("tracks", migration 008) ----------
# Public contract (adopted with the frontend 2026-10-02): boxes are NORMALISED [x, y, w, h] (0-1, top-left
# origin); frames are 0-based at the native fps, t = f / fps.
TrackStatus = Literal["queued", "processing", "done", "failed"]
NormBox = list[float]


def _check_norm_box(b: Optional[list[float]]) -> Optional[list[float]]:
    if b is None:
        return None
    if not all(math.isfinite(v) for v in b):
        raise ValueError("bbox values must be finite numbers")
    x, y, w, h = b
    eps = 1e-3
    if not (w > 0 and h > 0):
        raise ValueError("bbox must be [x, y, w, h] with w > 0 and h > 0")
    if x < -eps or y < -eps or x + w > 1 + eps or y + h > 1 + eps:
        raise ValueError("bbox must be normalised [x, y, w, h] inside the frame (0-1, top-left origin)")
    return b


class TrackCreateIn(BaseModel):
    """POST /api/videos/{id}/tracks. Needs ONE of: bbox + (frame or t) | player_id | jersey_number.
    When several are given, bbox wins over player_id, which wins over jersey_number; the others are kept as
    labels (e.g. the clicked detection's player_id / jersey_number / team). team is always optional.
    Unknown fields are ignored."""
    model_config = ConfigDict(extra="ignore")

    frame: Optional[StrictInt] = Field(None, ge=0, description="0-based frame index at the native fps (or give t)")
    t: Optional[float] = Field(None, ge=0, description="Seconds into the clip (or give frame)")
    bbox: Optional[NormBox] = Field(None, min_length=4, max_length=4,
                                    description="[x, y, w, h] normalised 0-1, top-left origin")
    player_id: Optional[Annotated[StrictInt, Field(ge=1)]] = Field(None, description="App player id (from detections)")
    jersey_number: Optional[Annotated[StrictInt, Field(ge=0, le=99)]] = Field(None, description="Shirt number 0-99")
    team: Optional[Literal["A", "B"]] = Field(None, description="CV team label A | B (optional)")

    @field_validator("team", mode="before")
    @classmethod
    def _team_upper(cls, v):
        if isinstance(v, str):
            v = v.strip().upper()
            return v or None
        return v

    @model_validator(mode="after")
    def _target(self):
        if self.t is not None and not math.isfinite(self.t):
            raise ValueError("t must be a finite number of seconds")
        if self.t is not None and self.frame is not None:
            raise ValueError("give frame or t, not both")
        _check_norm_box(self.bbox)
        if self.bbox is not None and self.frame is None and self.t is None:
            raise ValueError("bbox needs the frame (or t) it was drawn on")
        if self.bbox is None and self.player_id is None and self.jersey_number is None:
            raise ValueError("give bbox + frame (or t), or player_id, or jersey_number")
        return self

    @property
    def mode(self) -> str:
        return "bbox" if self.bbox is not None else ("player" if self.player_id is not None else "jersey")


class TrackTargetOut(BaseModel):
    mode: Literal["bbox", "player", "jersey"]
    player_id: Optional[int] = None
    jersey_number: Optional[int] = None
    team: Optional[Literal["A", "B"]] = None
    frame: Optional[int] = None
    t: Optional[float] = None
    bbox: Optional[NormBox] = Field(None, description="[x, y, w, h] normalised 0-1 on `frame`")


class TrackOut(BaseModel):
    track_id: int
    video_id: int
    status: TrackStatus
    stage: str = Field(description="queued | detect | tracking | rendering | done | failed")
    progress: int
    error_message: Optional[str] = None
    error_code: Optional[str] = Field(None, description="target_not_found | cv_unavailable | cv_failed | timeout | "
                                                        "interrupted | source_missing | bad_output (failed tracks)")
    target: TrackTargetOut
    fps: Optional[float] = None
    frame_count: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    annotated_url: Optional[str] = Field(None, description="When done: annotated MP4 with a short-lived ?token= "
                                                           "(use as <video src>; Range supported). null until done")
    frames_url: str = Field(description="Per-frame boxes, with a short-lived ?token= (409 until done)")
    source: Optional[Literal["real", "stub"]] = Field(None, description="When done: 'stub' = fake demo track")
    summary: Optional[dict[str, Any]] = Field(None, description="When done: tracked/occluded/lost frame counts, "
                                                                "coverage_pct, avg_conf, reacquisition_count, "
                                                                "lost_segments [[first, last], ...]")
    stats: Optional[dict[str, Any]] = Field(None, description="target_stats.json (player_match_stats-shaped) or null")
    warnings: list[str] = []
    created_at: UTCDateTime
    updated_at: UTCDateTime
    finished_at: Optional[UTCDateTime] = None


class DetectionOut(BaseModel):
    player_id: Optional[int] = None
    jersey_number: Optional[int] = None
    team: Optional[Literal["A", "B"]] = None
    class_: Literal["player", "goalkeeper", "referee"] = Field("player", alias="class", serialization_alias="class")
    bbox: NormBox = Field(description="[x, y, w, h] normalised 0-1, top-left origin")
    conf: float
    # ERD / pixel shapes (v0.6.0); derived from bbox × frame size (or stored detection corners)
    bbox_xyxy: Optional[list[float]] = Field(None, description="[x1,y1,x2,y2] pixels")
    x_center: Optional[float] = None
    y_center: Optional[float] = None
    bbox_width: Optional[float] = None
    bbox_height: Optional[float] = None
    model_config = ConfigDict(populate_by_name=True)


class DetectionsOut(BaseModel):
    frame: int
    t: float
    width: int
    height: int
    frame_url: str
    source: Literal["real", "stub"]
    players: list[DetectionOut]


class TrackFrameOut(BaseModel):
    f: int
    t: float
    bbox: Optional[NormBox] = None
    conf: float
    state: Literal["tracked", "occluded", "lost"]
    pitch_x: Optional[float] = None
    pitch_y: Optional[float] = None


class TrackFramesOut(BaseModel):
    track_id: int
    source: Literal["real", "stub"]
    fps: float
    width: int
    height: int
    frame_count: int
    start: int
    end: int
    frames: list[TrackFrameOut]
