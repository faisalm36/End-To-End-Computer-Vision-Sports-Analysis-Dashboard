# Architecture

Soccer video analytics for the capstone. A coach uploads match footage. A computer-vision pipeline detects and tracks
players, and the backend stores per-player stats, metrics and heatmaps that the React dashboard shows. API
details are in [API.md](API.md).

> **CV pipeline ownership.** The detection, tracking, OCR, calibration and metric maths belong to the CV pipeline
> (`cv/run_pipeline.py`, [GitHub PR #1](https://github.com/faisalm36/End-To-End-Computer-Vision-Sports-Analysis-Dashboard/pull/1), branch `cursor/soccer-cv-pipeline-236d`). The `cv/` folder **isn't in this
> checkout yet**. When it's merged, its own docs (`cv/README.md` and the files under `cv/`) are the source of truth for
> anything CV-specific. This document only covers the backend's side of that contract (how the backend calls the
> pipeline and which output files it reads), as implemented in `backend/pipeline.py`.

## 1. System overview

```mermaid
flowchart LR
    subgraph Browser
        FE["React 19 + Vite SPA<br/>frontend/ (port 5173)<br/>react-router, Tailwind v4"]
    end
    subgraph Backend["FastAPI backend (backend/, uvicorn port 8000)"]
        API["HTTP API<br/>main.py + routers/*<br/>JWT auth (security.py)"]
        BG["Background worker<br/>FastAPI BackgroundTasks<br/>pipeline.process_video()<br/>tracking.process_track()"]
        FS[("uploads/<br/>videos, thumbnails/,<br/>cv_outputs/video_ID/, track_ID/,<br/>frames/video_ID/")]
    end
    DB[("MySQL 8+ / 26.x<br/>soccer_analytics_* schema<br/>SQLAlchemy 2 + PyMySQL")]
    CV["CV pipeline (PR #1)<br/>python -m cv.run_pipeline<br/>cv.detect_frame / cv.track_player<br/>separate venv (CV_PYTHON)"]
    STUB["Stub generator<br/>(fake demo data)"]

    FE -- "fetch JSON, Bearer JWT<br/>VITE_API_URL" --> API
    API -- "ORM sessions" --> DB
    API -- "save upload" --> FS
    API -- "add_task(process_video / process_track)" --> BG
    API -- "detections: cv.detect_frame (sync, cached)" --> CV
    BG -- "subprocess, --video --out" --> CV
    BG -. "CV_PIPELINE_MODE=stub/auto fallback" .-> STUB
    CV -- "JSON files" --> FS
    STUB -- "same JSON files" --> FS
    BG -- "read outputs, ingest rows,<br/>stage/progress updates" --> DB
```

- **One process.** The worker runs inside the uvicorn process (Starlette `BackgroundTasks`, executed in the threadpool
  after the 202 response). There's no queue or broker. If the server stops mid-processing, the next startup marks
  the interrupted videos `failed` (`fail_interrupted_videos()` in `main.py`), so upload them again.
- **CV isolation.** The real pipeline runs as a **subprocess** (`cd <repo root> && PYTHONPATH=<repo root> <CV_PYTHON> -m
  cv.run_pipeline --video <file> --out <dir> --device <CV_DEVICE> [--calibration ...] [--model ...] [CV_EXTRA_ARGS]`),
  so its heavy dependencies (torch, ultralytics, easyocr) never load into the API process. Its log output is parsed into
  `stage`/`progress` hints. It's killed after `CV_TIMEOUT_SECONDS`, or when its video is deleted.
- **Pipeline modes** (`CV_PIPELINE_MODE`): `real` = always the real pipeline. `stub` = always fake demo data.
  `auto` = real if `CV_PIPELINE_PATH` exists, else stub if `CV_PIPELINE_STUB=true`, else the video fails with a clear
  `error_message`. The mode in use is logged at startup (`CV pipeline mode: ...`), and `pipeline_meta.adapter_source`
  records `real` or `stub` on each video.
- **Player tracking** (v0.5.0, `backend/tracking.py`): `cv.detect_frame` runs synchronously for
  `GET /api/videos/{id}/detections` (result cached per video + frame in `cv_outputs/frames/video_<id>/frame_<n>/`), and
  `cv.track_player` runs in the background per `player_tracks` row (outputs in `cv_outputs/track_<track_id>/`).
  Same isolation as the main pipeline (subprocess, `CV_PYTHON`, cwd = repo root). The CV interface is pixel-based;
  the backend converts to the public "tracks" contract agreed with the frontend (normalised `[x, y, w, h]` boxes,
  0-based frames at the native fps, per-frame `state` tracked / occluded / lost). Mode: `TRACK_PIPELINE_MODE`,
  independent of `CV_PIPELINE_MODE`: `auto` (default) = real only if both `cv/track_player.py` and
  `cv/detect_frame.py` exist under the CV repo root, else the stub (so it switches to real once the CV tracking PR
  lands); `real` / `stub` force one. The stub uses the video's stored detections for the frame when there are any,
  fakes a track and renders a real H.264 annotated MP4 with ffmpeg (same fps and frame count as the source). One
  active track per video; interrupted tracks are marked failed at startup. The CV interface (flags, files, exit code
  3 = target not found) is owned by the CV pipeline and documented in the `tracking.py` docstring.

## 2. Component responsibilities

| Component | Files | Responsibility |
|---|---|---|
| App entry | `backend/main.py` | FastAPI app, CORS, routers, `/health`, public `/api/players/stats` and `/api/players/{id}`, error handlers (DB down → 503, unexpected → 500). At startup it warns about a placeholder `JWT_SECRET`, logs the CV mode, marks interrupted videos and player tracks `failed` and upserts the metric registry (`ensure_definitions()`) |
| Settings | `backend/config.py` | pydantic-settings: environment variables > `backend/.env` > defaults (see §6) |
| DB layer | `backend/database.py`, `backend/models.py` | Engine/session (`pool_pre_ping`, 3 s MySQL connect timeout, UTC session time zone), ORM models for all 15 tables |
| Auth | `backend/security.py`, `backend/routers/auth.py` | bcrypt password hashes, HS256 JWT access tokens, register/login/token/me/change-password |
| Videos | `backend/routers/videos.py`, `backend/thumbnails.py` | Upload validation (size, extension, MIME, file signature), match find-or-create, background processing, status, stats, heatmaps, thumbnails (ffmpeg or OpenCV), per-video player corrections (`PATCH /api/videos/{id}/players/{player_id}`), delete with file cleanup (and the match's tags when it was the match's last video) |
| Player tracking | `backend/tracking.py`, `backend/routers/tracking.py`, `backend/media.py` | Frame still + detections (`/frame`, `/detections`), tracks (`/api/videos/{id}/tracks`, `/api/tracks/...` incl. `/frames` and `/annotated.mp4`), the original video (`/api/videos/{id}/source`, `source_url`), the CV adapter for `cv.detect_frame` / `cv.track_player` (command builders isolated at the top), pixel → normalised conversion and `state` mapping, `target_stats.json` → `stats`, the stub (fake track + ffmpeg annotated MP4), HTTP Range streaming and scoped media tokens (`media.py`) |
| CV adapter | `backend/pipeline.py` | `process_video()`: runs the real CV pipeline or the stub, reads its JSON outputs defensively, maps tracks to players (jersey OCR or placeholder "Unknown #n"), replaces this video's stats/detections/metrics/heatmaps in one transaction, stage/progress |
| Metrics | `backend/metrics_catalog.py`, `backend/routers/metrics.py` | Registry of per-player metrics (label, unit, aggregation rule, availability), multi-video aggregation, player history and heatmaps |
| Aggregates | `backend/stats.py` | Per-player aggregate (max speed, total distance, worst injury risk) used by `/api/players/stats` and `/api/videos/{id}/stats`; applies per-video jersey overrides to that video's rows |
| Matches & tags | `backend/routers/matches.py`, `backend/routers/tags.py`, `backend/tagging.py`, `backend/match_logic.py` | Scores and W/D/L result (derived from score + `our_side`), user-scoped tags (key/value) on matches |
| Insights | `backend/routers/insights.py` | Compares per-match averages across the values of one tag key (e.g. weather: Windy vs Rainy), with the next-match effect and a low-sample flag |
| Meta | `backend/routers/meta.py` | `/api/config`: upload limits and allowed types for the frontend |
| Frontend | `frontend/src/` | Pages: Landing, Login, Signup, ForgotPassword, Dashboard (`/api/players/stats`), Upload, VideoResults (`/videos/:id`), Insights, Profile. `lib/api.js` holds the API client (base URL from `VITE_API_URL`, token in `localStorage`). Protected routes need a JWT |
| Schema & migrations | `backend/schema.sql`, `backend/migrations/000-008` | Fresh install vs in-place upgrade of an existing database (see §7) |
| Tests | `backend/tests/` | pytest on a throwaway SQLite DB with temp dirs; never touches MySQL, `.env` or `uploads/` (see `tests/conftest.py`) |

## 3. Data flow: upload → CV → DB → dashboard

```mermaid
sequenceDiagram
    autonumber
    actor Coach
    participant FE as React (Upload / VideoResults)
    participant API as FastAPI routers/videos.py
    participant FS as uploads/
    participant DB as MySQL
    participant W as Worker pipeline.process_video
    participant CV as CV pipeline (subprocess) or stub

    Coach->>FE: choose file + match info + tags
    FE->>API: POST /api/videos (multipart, Bearer)
    API->>API: validate size / extension / MIME / magic bytes
    API->>FS: stream file to uploads/<uuid>.<ext>
    API->>DB: find-or-create teams + match, tags, INSERT match_videos (queued, 0%)
    API-->>FE: 202 {id, status: queued, stage: queued, progress: 0}
    API->>W: BackgroundTasks.add_task(process_video, id)
    W->>DB: status=processing, stage=detect, progress=10
    W->>FS: thumbnail (ffmpeg / OpenCV, optional, never fails the video)
    W->>CV: python -m cv.run_pipeline --video ... --out uploads/cv_outputs/video_<id>/
    loop while running
        CV-->>W: log lines → stage/progress hints
        W->>DB: set_progress(stage, progress) (never moves backwards)
        FE->>API: GET /api/videos/{id} (poll)
        API-->>FE: {status, stage, progress}
    end
    CV->>FS: tracking_detections.json, player_match_stats.json, meta.json, heatmaps.json (v1.2.0)
    W->>DB: stage=metrics (80), then ingest (90)
    W->>DB: replace this video's player_match_stats, tracking_detections, player_match_metrics, player_heatmaps
    W->>DB: status=done, stage=done, progress=100, processed_at, pipeline_meta
    FE->>API: GET /api/videos/{id}/stats?include=metrics, /heatmap
    API->>DB: aggregate per player (stats.py, metrics_catalog.py)
    API-->>FE: per-player stats, metrics, heatmap grids
    FE->>API: GET /api/players/stats, /api/insights?tag_key=...
    API-->>FE: dashboard + insights data
    Note over W,DB: Any exception → status=failed, stage=failed, error_message (stats endpoints then return 409)
```

### Player tracking: pick a player → background track → replay (v0.5.0)

```mermaid
sequenceDiagram
    autonumber
    actor Coach
    participant FE as React (Track a player)
    participant API as FastAPI routers/tracking.py
    participant FS as uploads/cv_outputs/
    participant DB as MySQL
    participant W as Worker tracking.process_track
    participant CV as cv.detect_frame / cv.track_player (subprocess) or stub

    Coach->>FE: scrub to a moment (pick mode)
    FE->>API: GET /api/videos/{id}/detections?frame=120 (Bearer)
    alt frames/video_<id>/frame_<n>/ cached
        API->>FS: read detections_api.json
    else first request for that frame
        API->>CV: python -m cv.detect_frame --video ... --t ... --out ...
        CV->>FS: frame.jpg, candidates.json (pixels)
        API->>DB: match stored tracking_detections (IoU) → player_id
    end
    API-->>FE: {frame, t, width, height, frame_url (?token=), players[{player_id, jersey_number, team, class, bbox [x,y,w,h] 0-1, conf}]}
    FE->>API: GET frame_url (<img src>, media token)
    Coach->>FE: click a box (or pick a player / shirt number)
    FE->>API: POST /api/videos/{id}/tracks {frame, bbox} | {player_id} | {jersey_number, team?}
    API->>DB: video done? no active track? INSERT player_tracks (queued, fps/frame_count/width/height)
    API-->>FE: 202 full track object (frames_url, annotated_url null)
    API->>W: BackgroundTasks.add_task(process_track, track_id)
    W->>CV: python -m cv.track_player --video ... --out track_<track_id>/ (--frame --bbox px | --jersey [--team])
    loop while running
        CV-->>W: "Processing frames: N%" → stage=tracking, progress
        FE->>API: GET /api/tracks/{track_id} (poll 1-2 s)
    end
    CV->>FS: track.json, replay.mp4, meta.json, target_stats.json (optional)
    W->>FS: frames_api.json (dense, normalised frames + summary)
    W->>DB: status=done, paths, meta, stats (exit code 3 → failed, error_code target_not_found)
    FE->>API: GET /api/tracks/{track_id} → annotated_url (?token=), frames_url (?token=)
    FE->>API: GET annotated_url (<video src>, Range: bytes=...) → 206 partial content
    FE->>API: GET frames_url&start=&end= → per-frame boxes for the canvas overlay on source_url
```

Output files the backend reads (field names are owned by the CV pipeline; every field is read defensively and new
fields are ignored): `tracking_detections.json` (per-frame boxes, track ids, `-1` = ball, pitch coordinates,
jersey OCR), `player_match_stats.json` (per-track speed, distance, sprints, workload-based injury risk; v1.2.0 adds
minutes, coverage, zones, accelerations), `meta.json` (fps, duration, model, device, calibration, thresholds,
warnings) and `heatmaps.json` (v1.2.0, seconds per cell on a 21×14 grid). Speed and distance are `null` without
calibration. See the module docstring of `backend/pipeline.py` for the exact contract the backend expects.

Backend rules on top of the CV output (v0.4.1):

- **Minutes and rates.** `minutes_played` / `visible_minutes` come from the pipeline per track (PR #2's
  `minutes_played_s` / `visible_minutes_s` seconds are preferred when present), else the clip length. `distance_per_min`
  = distance / tracked minutes (else minutes played) and is `null` when those minutes are under
  `MIN_RATE_MINUTES` = 0.1 (`metrics_catalog.py`). The same floor applies when the API reads stored rows, so values
  stored by older versions (e.g. 438,000 m/min on a 1 s clip) are hidden without a backfill.
- **Speed thresholds.** `GET /api/videos/{id}/stats` always returns `speed_thresholds`: the video's `meta.json` values,
  with any missing key filled from `DEFAULT_SPEED_THRESHOLDS` (the CV config: preset `gps_standard`, HSR 19.8 km/h,
  sprint 25.3 km/h as the pipeline writes it from 15.7 mph, zone edges walk 7 / jog 15 / run 19.8 / hsr 25.3).
  `source` says `pipeline`, `default` or `mixed`.
- **Stub.** The stub derives the clip length from the uploaded file (ffprobe, else OpenCV; 1 s if unreadable), minutes
  from the frames each fake player is visible, and distance from 85-125 m/min, so its numbers are consistent.
- **CV PR #2 tolerance** (not merged; `player_uid` keying is not integrated yet): `heatmaps.json` = `{}` falls back to
  backend grids without a warning; `distance_m`, `player_uid`, `contributing_track_ids`, `detected_frames`,
  `total_frames` are accepted; `team` may be `0`/`1` or `"A"`/`"B"`.

## 4. Database (ERD of the current `backend/schema.sql`)

15 tables, InnoDB, `utf8mb4_unicode_ci`, signed `INT` keys. Every foreign key cascades on delete, except
`tracking_detections.player_id` and `player_tracks.player_id`, which are set to NULL.

```mermaid
erDiagram
    users ||--o{ teams : owns
    users ||--o{ match_videos : uploads
    users ||--o{ tag_keys : defines
    teams ||--o{ players : has
    teams ||--o{ matches : "home_team_id"
    teams ||--o{ matches : "away_team_id"
    matches ||--o{ match_videos : "recorded in"
    matches ||--o{ player_match_stats : "stats for"
    matches ||--o{ match_tags : tagged
    players ||--o{ player_match_stats : has
    players |o--o{ tracking_detections : "identified as"
    match_videos ||--o{ player_match_stats : produces
    match_videos ||--o{ tracking_detections : contains
    player_match_stats ||--o{ player_match_metrics : "extended metrics"
    player_match_stats ||--o| player_heatmaps : heatmap
    metric_definitions ||--o{ player_match_metrics : defines
    tag_keys ||--o{ tag_values : has
    tag_values ||--o{ match_tags : "applied as"
    match_videos ||--o{ video_player_overrides : corrects
    players ||--o{ video_player_overrides : "per-video jersey"
    match_videos ||--o{ player_tracks : "tracked in"
    users ||--o{ player_tracks : starts
    players |o--o{ player_tracks : "target (optional)"

    users {
        int user_id PK
        varchar first_name
        varchar last_name
        varchar email UK
        varchar password_hash
        varchar role "default analyst"
        datetime created_at
    }
    teams {
        int team_id PK
        int user_id FK
        varchar team_name
        varchar league
    }
    players {
        int player_id PK
        int team_id FK
        varchar first_name
        varchar last_name
        int jersey_number "UK with team_id"
        varchar position
        enum dominant_foot "Left|Right|Both"
    }
    matches {
        int match_id PK
        int home_team_id FK
        int away_team_id FK
        date match_date
        varchar stadium_name
        varchar weather_condition
        varchar tactical_formation
        int home_score
        int away_score
        enum our_side "home|away"
        enum result "W|D|L"
    }
    match_videos {
        int video_id PK
        int match_id FK
        int user_id FK
        varchar title
        varchar file_name
        varchar file_path
        float fps
        enum processing_status "queued|processing|done|failed"
        varchar stage
        int progress "0-100"
        text error_message
        varchar thumbnail_path
        text pipeline_meta "JSON"
        datetime uploaded_at
        datetime processed_at
    }
    player_match_stats {
        int stat_id PK
        int player_id FK "UK with video_id"
        int match_id FK
        int video_id FK
        decimal top_speed_mph
        decimal distance_km
        enum injury_risk "Low|Medium|High"
    }
    tracking_detections {
        bigint detection_id PK
        int video_id FK
        int player_id FK
        int track_id "-1 = ball"
        int frame_number
        varchar object_class
        int jersey_number
        float bbox_x1
        float bbox_y1
        float bbox_x2
        float bbox_y2
        float confidence
        float pitch_x
        float pitch_y
    }
    metric_definitions {
        varchar metric_key PK
        varchar label
        varchar unit
        varchar category
        varchar value_type
        varchar aggregation "sum|max|min|avg|ratio"
        varchar ratio_numerator
        varchar ratio_denominator
        double ratio_scale
        int decimals
        tinyint higher_is_better
        tinyint requires_calibration
        tinyint is_estimate
        varchar availability "ready|soon"
        varchar storage "column|metric"
        varchar description
        int sort_order
        tinyint is_active
    }
    player_match_metrics {
        int stat_id PK, FK
        varchar metric_key PK, FK
        double value
    }
    player_heatmaps {
        int stat_id PK, FK
        int grid_cols
        int grid_rows
        double pitch_length_m
        double pitch_width_m
        int samples
        text cells "JSON grid"
        varchar source "pipeline|backend"
        varchar cell_unit "seconds|samples"
    }
    tag_keys {
        int tag_key_id PK
        int user_id FK "UK with name"
        varchar name
        datetime created_at
    }
    tag_values {
        int tag_value_id PK
        int tag_key_id FK "UK with value"
        varchar value
        datetime created_at
    }
    match_tags {
        int match_id PK, FK
        int tag_value_id PK, FK
        datetime created_at
    }
    video_player_overrides {
        int video_id PK, FK
        int player_id PK, FK
        int jersey_number "0-99 or NULL"
        datetime updated_at
    }
    player_tracks {
        int track_id PK
        int video_id FK
        int user_id FK
        varchar target_mode "bbox | player | jersey"
        int init_frame "0-based at native fps"
        float init_t
        float bbox_x "normalised 0-1"
        float bbox_y
        float bbox_w
        float bbox_h
        int player_id FK "nullable, SET NULL"
        int jersey_number
        varchar team "A | B | NULL"
        float fps
        int frame_count
        int width
        int height
        enum status "queued|processing|done|failed"
        varchar stage "queued|detect|tracking|rendering|done|failed"
        int progress "0-100"
        text error_message "code: message"
        varchar output_dir
        varchar frames_path
        varchar annotated_path
        text meta "JSON summary"
        text stats "JSON target_stats or NULL"
        datetime created_at
        datetime updated_at
        datetime finished_at
    }
```

**Deletes.** Deleting a video removes its stats, detections, metrics, heatmaps, per-video overrides and player tracks
(FK cascade), its files (upload, thumbnail, `cv_outputs/video_<id>/`, cached frames, every `track_<track_id>/`), and its
per-track placeholder players. `DELETE /api/tracks/{track_id}` removes one track and its folder. Tags hang off the match, so when the deleted video was the match's
**last** video and no other stats reference the match (e.g. legacy rows without a video), the user's tags on that
match are removed too; otherwise they stay. The match row itself (teams, date, score/result) is kept, as before.

**Per-video corrections.** `video_player_overrides` holds a jersey number for a player *in one video*
(`PATCH /api/videos/{id}/players/{player_id}`). It overrides `players.jersey_number` in that video's stats only and
never rewrites the roster, which stays correct when the CV pipeline's `player_uid` keying (PR #2) lands.

## 5. Security model

- Passwords are bcrypt-hashed. JWT access tokens (HS256, `JWT_SECRET`) last `ACCESS_TOKEN_EXPIRE_MINUTES`. The SPA
  keeps the token in `localStorage` and logs out when it expires.
- Every video, match, tag and player-history query is filtered by the current user. Other users' rows return 404.
- `<img>` thumbnails can't send headers, so `thumbnail_url` carries a short-lived token scoped to that one video
  (`THUMBNAIL_TOKEN_EXPIRE_MINUTES`).
- `<img>` frame stills, `<video>` sources/annotated videos and the per-frame JSON use the same idea: `source_url`,
  `frame_url`, `annotated_url` and `frames_url` carry a short-lived media token (`MEDIA_TOKEN_EXPIRE_MINUTES`) with one
  scope: `source:<video_id>`, `frame:<video_id>` or `track:<track_id>`. Media tokens can't be used as
  a login, and access tokens are never accepted in a query string.
- CORS allows only `CORS_ORIGINS` (default `http://localhost:5173`, `http://127.0.0.1:5173`). That's why Vite runs
  with `strictPort: true`.
- Not user-scoped (by design, for the public dashboard): `GET /api/players/stats` and `GET /api/players/{id}`.

## 6. Configuration

Backend settings come from `backend/config.py`. They're read from environment variables first, then
`backend/.env` (gitignored; copy `backend/.env.example`), then the defaults. Setting `BACKEND_ENV_FILE` to a path
changes which `.env` is read; setting it to an empty string skips `.env` entirely (the test suite does this).

| Key | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `mysql+pymysql://root:password@localhost:3306/soccer_analytics_db` | SQLAlchemy URL (MySQL in dev/prod; tests force SQLite) |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Allowed browser origins |
| `SQL_ECHO` | `false` | Log SQL |
| `JWT_SECRET` | placeholder (a startup warning is logged) | HS256 signing key, at least 32 characters |
| `JWT_ALGORITHM` | `HS256` | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Login token lifetime |
| `THUMBNAIL_TOKEN_EXPIRE_MINUTES` | `60` | Lifetime of the `?token=` in `thumbnail_url` |
| `MEDIA_TOKEN_EXPIRE_MINUTES` | `60` | Lifetime of the `?token=` in `source_url` / `frame_url` / `frames_url` / `annotated_url` |
| `UPLOAD_DIR` | `backend/uploads` | Uploaded videos |
| `MAX_UPLOAD_MB` | `500` | Upload limit (413 above it), also exposed through `/api/config` |
| `ALLOWED_VIDEO_EXTENSIONS` | `mp4,mov,avi,mkv` | Accepted extensions (415 otherwise). The code default is the intended set (each is checked by file signature; ffmpeg probes/thumbnails all four). The frontend uses the server list from `/api/config`; its own offline fallback is only mp4/mov |
| `THUMBNAILS_ENABLED` | `true` | Grab a frame with ffmpeg (preferred) or OpenCV; never fails processing |
| `THUMBNAIL_DIR` | `backend/uploads/thumbnails` | |
| `CV_PIPELINE_MODE` | `auto` | `auto` / `real` / `stub` (see §1) |
| `CV_PIPELINE_STUB` | `false` | In `auto` mode: use the stub when the real pipeline is missing |
| `CV_PIPELINE_PATH` | `<repo>/cv/run_pipeline.py` | Locates the CV checkout (the file, the `cv/` dir, or the repo root) |
| `CV_PYTHON` | backend's Python | Interpreter with the CV dependencies (its own venv) |
| `CV_DEVICE` | `auto` | `auto` / `cuda` / `mps` / `cpu` |
| `CV_MODEL` | pipeline default | YOLO weights |
| `CV_CALIBRATION_PATH` | none | Pitch calibration JSON (needed for real speed/distance) |
| `CV_EXTRA_ARGS` | empty | Extra CLI flags for the pipeline |
| `CV_TIMEOUT_SECONDS` | `14400` | Kill the pipeline after this long |
| `CV_OUTPUT_DIR` | `backend/uploads/cv_outputs` | Per-video pipeline output folders |
| `CV_CREATE_UNKNOWN_PLAYERS` | `true` | Unmatched tracks get placeholder players ("Unknown #n") |
| `TRACK_PIPELINE_MODE` | `auto` | Player tracking, independent of `CV_PIPELINE_MODE`: `auto` = real only if `cv/track_player.py` and `cv/detect_frame.py` both exist, else stub; `real` / `stub` force one |
| `CV_TRACK_TIMEOUT_SECONDS` | `7200` | Kill `cv.track_player` after this long |
| `CV_DETECT_TIMEOUT_SECONDS` | `180` | Kill `cv.detect_frame` after this long (the detections request then returns 504) |

Frontend (`frontend/.env`, optional; see `frontend/.env.example`): `VITE_API_URL` (default `http://localhost:8000`)
and `VITE_MAX_UPLOAD_MB` (fallback only; the real limit comes from `/api/config`).

## 7. Setup

Prerequisites: Python 3.11–3.13, MySQL 8.0+ (tested on 26.7), Node 20.19+ or 22.12+ (required by Vite 8) with npm, and ffmpeg (optional, for
thumbnails).

```bash
# 1. Database: pick ONE
mysql -u root -p < backend/schema.sql                       # A) fresh install
#    B) existing database: back it up, then run backend/migrations/000 ... 008 in order (each is idempotent)
#       full instructions: backend/README.md ("Database: pick ONE of these")

# 2. Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # set DATABASE_URL, JWT_SECRET, CV_* (CV_PIPELINE_STUB=true for demo data without CV)
.venv/bin/python seed.py    # OPTIONAL: wipes ALL rows and loads demo data (login faisal@example.com / capstone123)

# 3. Frontend
cd ../frontend && npm install    # optional: cp .env.example .env

# 4. Run both (checks prerequisites and ports, Ctrl+C stops both)
cd .. && scripts/dev.sh          # backend http://localhost:8000 (docs at /docs), frontend http://localhost:5173
```

Tests: `cd backend && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/python -m pytest -q` (SQLite in a
temp dir; MySQL isn't needed and is never contacted). API docs: `backend/.venv/bin/python scripts/gen_api_docs.py`
regenerates [API.md](API.md).
