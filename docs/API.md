# API reference

Generated from the backend code (FastAPI app `Soccer Video Analytics API` v0.5.1) by `scripts/gen_api_docs.py`. Every response example below is a real response, recorded against a throwaway SQLite database loaded with `backend/seed.py` and using the **stub** CV pipeline, so the numbers are demo data. Long lists are shortened (`"... N more"`). Regenerate after any API change:

```bash
backend/.venv/bin/python scripts/gen_api_docs.py
```

Interactive docs from the running server: `http://localhost:8000/docs` (Swagger), `/redoc`, `/openapi.json`.

## Conventions

- **Base URL**: `http://localhost:8000` in development (the frontend reads it from `VITE_API_URL`).
- **Auth**: `Authorization: Bearer <access_token>`. Get the token from `POST /api/auth/login` (JSON) or `POST /api/auth/register`. Tokens are HS256 JWTs, valid for `ACCESS_TOKEN_EXPIRE_MINUTES` (default 60). There is no refresh endpoint; log in again when you get a 401.
- **Ownership**: videos, matches, tags and player history are per-user. Anything that belongs to another user returns **404**, not 403, so it's impossible to tell whether it exists.
- **Public (no token)**: `/health`, `/api/config`, `/api/metrics`, `/api/players/stats`, `/api/players/{player_id}`, `/api/auth/register|login|token`. Note that `/api/players/stats` and `/api/players/{id}` are not user-scoped: they return every player in the database.
- **Timestamps** are UTC ISO-8601 with `Z`. **Units**: speeds in mph (`*_kmh` variants where noted), distances in km, pitch coordinates in metres.
- **Rates and thresholds**: `distance_per_min` (m/min) is `null` when the player's tracked (else played) minutes are under 0.1, so short clips never produce absurd rates. `speed_thresholds` on video stats always has values: from the video's `meta.json`, or the CV defaults (`source: "default"`, or `"mixed"` when only some keys were present).
- **Player tracking** (`/detections`, `/frame`, `/api/videos/{id}/tracks`, `/api/tracks/...`): every box is **normalised** `[x, y, w, h]` (0-1, top-left origin; multiply by the `width` x `height` given in the response for pixels). Frames are **0-based at the native fps**, `t = f / fps`; the annotated MP4 has the same fps and frame count as the source (client sync: `f = round(currentTime * fps)`). Per-frame `state` is `tracked`, `occluded` (interpolated estimate, still has a bbox) or `lost` (`bbox: null`, `conf: 0`). Tracks run in the background (`queued` -> `processing` -> `done` | `failed`; stages `queued`, `detect`, `tracking`, `rendering`, `done` | `failed`; poll `GET /api/tracks/{track_id}` every 1-2 s), one active track per video. `source_url`, `frame_url`, `frames_url` and `annotated_url` are relative and carry a short-lived `?token=` (`MEDIA_TOKEN_EXPIRE_MINUTES`, default 60) so they work directly as `<video src>` / `<img src>` / `fetch`; re-fetch the video / detections / track for a fresh URL after a 401. `/source` and `annotated.mp4` support HTTP Range (206 / 416) and HEAD. `source: "stub"` = fake demo data from the backend stub (until the CV tracking modules are installed). Failed tracks carry `error_code` (`target_not_found`, `cv_unavailable`, `cv_failed`, `timeout`, `interrupted`, `source_missing`, `bad_output`). Frontend contract: `CONTRACT_track_player.md` (adopted with the frontend team, 2026-10-02).
- **Errors** are JSON `{"detail": ...}`. Common shapes (all recorded live):

  - 401 `GET /api/videos` without a token: `{"detail": "Not authenticated"}`
  - 404 `GET /api/videos/999999`: `{"detail": "Video not found"}`
  - 409 `GET /api/videos/{id}/stats` before processing finishes: `{"detail": "Video not processed yet", "status": "queued", "stage": "queued", "progress": 0, "error_message": null}`
  - 422 validation error (FastAPI): `{"detail": [{"type": "value_error", "loc": ["body", "email"], "msg": "value is not a valid email address: An email address must have an @-sign.", "input": "not-an-email", "ctx": {"reason": "An email address must have an @-sign."}}]}` (one entry per invalid field)
  - 503 `{"detail": "Database unavailable"}` when MySQL can't be reached, and 500 `{"detail": "Internal server error"}` for unexpected errors. `/health` never fails; it reports `"db": "unreachable"` instead.

## Endpoints

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | [`/api/config`](#get-apiconfig) | public | Public Config |
| GET | [`/health`](#get-health) | public | Health |
| POST | [`/api/auth/change-password`](#post-apiauthchange-password) | Bearer | Change Password |
| POST | [`/api/auth/login`](#post-apiauthlogin) | public | Login |
| GET | [`/api/auth/me`](#get-apiauthme) | Bearer | Me |
| PATCH | [`/api/auth/me`](#patch-apiauthme) | Bearer | Update Me |
| POST | [`/api/auth/register`](#post-apiauthregister) | public | Register |
| POST | [`/api/auth/token`](#post-apiauthtoken) | public | Token |
| POST | [`/api/videos`](#post-apivideos) | Bearer | Upload Video |
| GET | [`/api/videos`](#get-apivideos) | Bearer | List Videos |
| GET | [`/api/videos/{video_id}`](#get-apivideosvideo_id) | Bearer | Get Video |
| DELETE | [`/api/videos/{video_id}`](#delete-apivideosvideo_id) | Bearer | Delete Video |
| GET | [`/api/videos/{video_id}/heatmap`](#get-apivideosvideo_idheatmap) | Bearer | Video Heatmap |
| PATCH | [`/api/videos/{video_id}/players/{player_id}`](#patch-apivideosvideo_idplayersplayer_id) | Bearer | Update Video Player |
| GET | [`/api/videos/{video_id}/stats`](#get-apivideosvideo_idstats) | Bearer | Video Stats |
| POST | [`/api/videos/{video_id}/tags`](#post-apivideosvideo_idtags) | Bearer | Add Video Tags |
| GET | [`/api/videos/{video_id}/tags`](#get-apivideosvideo_idtags) | Bearer | Get Video Tags |
| PUT | [`/api/videos/{video_id}/tags`](#put-apivideosvideo_idtags) | Bearer | Replace Video Tags |
| DELETE | [`/api/videos/{video_id}/tags`](#delete-apivideosvideo_idtags) | Bearer | Delete Video Tag |
| GET | [`/api/videos/{video_id}/thumbnail`](#get-apivideosvideo_idthumbnail) | Bearer | Video Thumbnail |
| GET | [`/api/matches`](#get-apimatches) | Bearer | List Matches |
| GET | [`/api/matches/{match_id}`](#get-apimatchesmatch_id) | Bearer | Get Match |
| PATCH | [`/api/matches/{match_id}`](#patch-apimatchesmatch_id) | Bearer | Patch Match |
| POST | [`/api/matches/{match_id}/tags`](#post-apimatchesmatch_idtags) | Bearer | Add Match Tags |
| GET | [`/api/matches/{match_id}/tags`](#get-apimatchesmatch_idtags) | Bearer | Get Match Tags |
| PUT | [`/api/matches/{match_id}/tags`](#put-apimatchesmatch_idtags) | Bearer | Replace Match Tags |
| DELETE | [`/api/matches/{match_id}/tags`](#delete-apimatchesmatch_idtags) | Bearer | Delete Match Tag |
| GET | [`/api/tags`](#get-apitags) | Bearer | All Tags |
| GET | [`/api/tags/keys`](#get-apitagskeys) | Bearer | Tag Keys |
| GET | [`/api/tags/values`](#get-apitagsvalues) | Bearer | Tag Values |
| GET | [`/api/metrics`](#get-apimetrics) | public | List Metrics |
| GET | [`/api/players/stats`](#get-apiplayersstats) | public | Player Stats |
| GET | [`/api/players/{player_id}`](#get-apiplayersplayer_id) | public | Get Player |
| GET | [`/api/players/{player_id}/heatmap`](#get-apiplayersplayer_idheatmap) | Bearer | Player Heatmap |
| GET | [`/api/players/{player_id}/metrics`](#get-apiplayersplayer_idmetrics) | Bearer | Player Metrics |
| GET | [`/api/insights`](#get-apiinsights) | Bearer | Insights |
| GET | [`/api/insights/tags`](#get-apiinsightstags) | Bearer | Insights Tags |
| GET | [`/api/videos/{video_id}/source`](#get-apivideosvideo_idsource) | Bearer | Video Source |
| GET | [`/api/videos/{video_id}/frame`](#get-apivideosvideo_idframe) | Bearer | Video Frame |
| GET | [`/api/videos/{video_id}/detections`](#get-apivideosvideo_iddetections) | Bearer | Video Detections |
| POST | [`/api/videos/{video_id}/tracks`](#post-apivideosvideo_idtracks) | Bearer | Create Track |
| GET | [`/api/videos/{video_id}/tracks`](#get-apivideosvideo_idtracks) | Bearer | List Tracks |
| GET | [`/api/tracks/{track_id}`](#get-apitrackstrack_id) | Bearer | Get Track |
| DELETE | [`/api/tracks/{track_id}`](#delete-apitrackstrack_id) | Bearer | Delete Track |
| GET | [`/api/tracks/{track_id}/frames`](#get-apitrackstrack_idframes) | Bearer | Get Track Frames |
| GET | [`/api/tracks/{track_id}/annotated.mp4`](#get-apitrackstrack_idannotatedmp4) | Bearer | Annotated Mp4 |

## Health & config

### GET /api/config

**Auth:** none (public)

Upload limits for the frontend (no auth).

**Example**

```http
GET /api/config
```

Response **200**:

```json
{
  "max_upload_mb": 500,
  "allowed_extensions": [
    "avi",
    "mkv",
    "... 2 more"
  ]
}
```

**Status codes:** `200`

### GET /health

**Auth:** none (public)

Liveness check. Never 500s: reports db='unreachable' if the DB is down.

**Example**

```http
GET /health
```

Response **200**:

```json
{
  "status": "ok",
  "db": "ok"
}
```

**Status codes:** `200`

## Auth

### POST /api/auth/change-password

**Auth:** Bearer token

**Request body** (`application/json`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `current_password` | string | yes |  |
| `new_password` | string | yes |  |

**Example**

```http
POST /api/auth/change-password
{
  "current_password": "supersecret1",
  "new_password": "evenmoresecret2"
}
```

Response **204** (no body)

**Status codes:** `204`; errors: 401 missing/invalid/expired Bearer token; 400 current password incorrect / new == current; 422 new password too short

### POST /api/auth/login

**Auth:** none (public)

JSON {"email","password"} (preferred) or an OAuth2-style form (username=<email>, password).

**Request body** (`application/json`)

**Request body** (`application/x-www-form-urlencoded`)

**Example**

```http
POST /api/auth/login
{
  "email": "faisal@example.com",
  "password": "capstone123"
}
```

Response **200**:

```json
{
  "access_token": "<JWT>",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "id": 1,
    "user_id": 1,
    "name": "Faisal Musa",
    "first_name": "Faisal",
    "last_name": "Musa",
    "email": "faisal@example.com",
    "role": "admin",
    "created_at": "2026-10-03T03:55:07Z"
  }
}
```

**Status codes:** `200`; errors: 401 incorrect email or password; 422 missing fields

### GET /api/auth/me

**Auth:** Bearer token

**Example**

```http
GET /api/auth/me
```

Response **200**:

```json
{
  "id": 1,
  "user_id": 1,
  "name": "Faisal Musa",
  "first_name": "Faisal",
  "last_name": "Musa",
  "email": "faisal@example.com",
  "role": "admin",
  "created_at": "2026-10-03T03:55:07Z"
}
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token

### PATCH /api/auth/me

**Auth:** Bearer token

**Request body** (`application/json`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string or null | no |  |
| `first_name` | string or null | no |  |
| `last_name` | string or null | no |  |

**Example**

```http
PATCH /api/auth/me
{
  "name": "Samantha Analyst"
}
```

Response **200**:

```json
{
  "id": 2,
  "user_id": 2,
  "name": "Samantha Analyst",
  "first_name": "Samantha",
  "last_name": "Analyst",
  "email": "sam@example.com",
  "role": "analyst",
  "created_at": "2026-10-03T03:55:08Z"
}
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token; 409 email already registered; 422 blank / too long names

### POST /api/auth/register

**Auth:** none (public)

201: the user object (as before) + access_token/token_type/expires_in + nested `user`.

**Request body** (`application/json`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `first_name` | string or null | no |  |
| `last_name` | string or null | no |  |
| `name` | string or null | no |  |
| `email` | string | yes |  |
| `password` | string | yes |  |

**Example**

```http
POST /api/auth/register
{
  "name": "Sam Analyst",
  "email": "sam@example.com",
  "password": "supersecret1"
}
```

Response **201**:

```json
{
  "id": 2,
  "user_id": 2,
  "name": "Sam Analyst",
  "first_name": "Sam",
  "last_name": "Analyst",
  "email": "sam@example.com",
  "role": "analyst",
  "created_at": "2026-10-03T03:55:08Z",
  "access_token": "<JWT>",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "id": 2,
    "user_id": 2,
    "name": "Sam Analyst",
    "first_name": "Sam",
    "last_name": "Analyst",
    "email": "sam@example.com",
    "role": "analyst",
    "created_at": "2026-10-03T03:55:08Z"
  }
}
```

**Status codes:** `201`; errors: 409 email already registered; 422 validation (password < 8 chars, bad email, names)

### POST /api/auth/token

**Auth:** none (public)

OAuth2 password form (username=<email>, password=...). Used by the /docs Authorize button.

**Request body** (`application/x-www-form-urlencoded`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `grant_type` | string or null | no |  |
| `username` | string | yes |  |
| `password` | string | yes |  |
| `scope` | string | no |  |
| `client_id` | string or null | no |  |
| `client_secret` | string or null | no |  |

**Example**

```http
POST /api/auth/token
{
  "username": "faisal@example.com",
  "password": "capstone123"
}
```

Response **200**:

```json
{
  "access_token": "<JWT>",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "id": 1,
    "user_id": 1,
    "name": "Faisal Musa",
    "first_name": "Faisal",
    "last_name": "Musa",
    "email": "faisal@example.com",
    "role": "admin",
    "created_at": "2026-10-03T03:55:07Z"
  }
}
```

**Status codes:** `200`; errors: 401 incorrect email or password; 422 missing fields

## Videos (upload, processing, results)

### POST /api/videos

**Auth:** Bearer token

**Request body** (`multipart/form-data`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `file` | string | yes | mp4 / mov / avi / mkv |
| `title` | string or null | no |  |
| `match_date` | string or null | no | YYYY-MM-DD |
| `home_team` | string or null | no |  |
| `away_team` | string or null | no |  |
| `our_side` | string or null | no | 'home' / 'away': which team is yours (for W/D/L) when both teams are yours; default home |
| `tags` | string or null | no | Optional JSON: [{"key":"weather","value":"Raining"}] (tags the match) |
| `match_id` | string or null | no | Attach to an existing match instead (integer; multipart sends it as a string, '' / 'null' / 'undefined' = not given) |

**Example**

```http
POST /api/videos
Content-Type: multipart/form-data
title=Derby first half
match_date=2026-09-20
home_team=Eagles FC
away_team=Riverside
our_side=home
tags=[{"key": "weather", "value": "Windy"}]
file=@derby.mp4 (video/mp4)
```

Response **202**:

```json
{
  "id": 6,
  "video_id": 6,
  "match_id": 8,
  "title": "Derby first half",
  "file_name": "derby.mp4",
  "match_date": "2026-09-20",
  "home_team": "Eagles FC",
  "away_team": "Riverside",
  "status": "queued",
  "stage": "queued",
  "progress": 0,
  "error_message": null,
  "error": null,
  "created_at": "2026-10-03T03:55:09Z",
  "uploaded_at": "2026-10-03T03:55:09Z",
  "processed_at": null,
  "fps": null,
  "duration_seconds": null,
  "thumbnail_url": null,
  "source_url": "/api/videos/6/source?token=<JWT>",
  "match": {
    "match_id": 8,
    "match_date": "2026-09-20",
    "home_team": "Eagles FC",
    "away_team": "Riverside",
    "home_score": null,
    "away_score": null,
    "result": null
  },
  "result": null,
  "tags": [
    {
      "key": "Weather",
      "value": "Windy"
    }
  ],
  "pipeline_meta": null
}
```

**Status codes:** `202`; errors: 401 missing/invalid/expired Bearer token; 404 match_id not yours; 413 file larger than MAX_UPLOAD_MB; 415 extension / content type / file signature not a video; 422 empty file, missing match info, home_team == away_team, bad tags JSON

### GET /api/videos

**Auth:** Bearer token

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `tag` | query | array | no | Filter by the match's tags, key:value, repeatable: same key = OR, different keys = AND, e.g. ?tag=weather:Raining&tag=pitch:Turf |

**Example**

```http
GET /api/videos
```

Response **200**:

```json
[
  {
    "id": 6,
    "video_id": 6,
    "match_id": 8,
    "title": "Derby first half",
    "file_name": "derby.mp4",
    "match_date": "2026-09-20",
    "home_team": "Eagles FC",
    "away_team": "Riverside",
    "status": "done",
    "stage": "done",
    "progress": 100,
    "error_message": null,
    "error": null,
    "created_at": "2026-10-03T03:55:09Z",
    "uploaded_at": "2026-10-03T03:55:09Z",
    "processed_at": "2026-10-03T03:55:09Z",
    "fps": 30.0,
    "duration_seconds": 1.0,
    "thumbnail_url": null,
    "source_url": "/api/videos/6/source?token=<JWT>",
    "match": {
      "match_id": 8,
      "match_date": "2026-09-20",
      "home_team": "Eagles FC",
      "away_team": "Riverside",
      "home_score": null,
      "away_score": null,
      "result": null
    },
    "result": null,
    "tags": [
      {
        "key": "Weather",
        "value": "Windy"
      }
    ]
  },
  {
    "id": 5,
    "video_id": 5,
    "match_id": 6,
    "title": "Sample match 6 (seed)",
    "file_name": "sample_match6.mp4",
    "match_date": "2026-09-19",
    "home_team": "Harbor City",
    "away_team": "Capstone FC",
    "status": "done",
    "stage": "done",
    "progress": 100,
    "error_message": null,
    "error": null,
    "created_at": "2026-10-03T03:55:07Z",
    "uploaded_at": "2026-10-03T03:55:07Z",
    "processed_at": null,
    "fps": 30.0,
    "duration_seconds": 3600.0,
    "thumbnail_url": null,
    "source_url": null,
    "match": {
      "match_id": 6,
      "match_date": "2026-09-19",
      "home_team": "Harbor City",
      "away_team": "Capstone FC",
      "home_score": 1,
      "away_score": 2,
      "result": "W"
    },
    "result": "W",
    "tags": [
      {
        "key": "Pitch",
        "value": "Grass"
      },
      {
        "key": "Weather",
        "value": "Sunny"
      }
    ]
  },
  "... 4 more"
]
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token; `422` invalid parameters

### GET /api/videos/{video_id}

**Auth:** Bearer token

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `video_id` | path | integer | yes |  |

**Example**

```http
GET /api/videos/6
```

Response **200**:

```json
{
  "id": 6,
  "video_id": 6,
  "match_id": 8,
  "title": "Derby first half",
  "file_name": "derby.mp4",
  "match_date": "2026-09-20",
  "home_team": "Eagles FC",
  "away_team": "Riverside",
  "status": "done",
  "stage": "done",
  "progress": 100,
  "error_message": null,
  "error": null,
  "created_at": "2026-10-03T03:55:09Z",
  "uploaded_at": "2026-10-03T03:55:09Z",
  "processed_at": "2026-10-03T03:55:09Z",
  "fps": 30.0,
  "duration_seconds": 1.0,
  "thumbnail_url": null,
  "source_url": "/api/videos/6/source?token=<JWT>",
  "match": {
    "match_id": 8,
    "match_date": "2026-09-20",
    "home_team": "Eagles FC",
    "away_team": "Riverside",
    "home_score": null,
    "away_score": null,
    "result": null
  },
  "result": null,
  "tags": [
    {
      "key": "Weather",
      "value": "Windy"
    }
  ],
  "pipeline_meta": {
    "fps": 30.0,
    "frame_count": 30,
    "duration_s": 1.0,
    "resolution": [
      1920,
      1080
    ],
    "model": "stub",
    "device": "none",
    "calibration": null,
    "pipeline_version": "stub-1",
    "runtime_s": 0.0,
    "warnings": [
      "STUB: fake demo data generated by backend/pipeline.py",
      "STUB: clip length unknown; assumed 1 s"
    ],
    "speed_preset": "gps_standard",
    "hsr_threshold_kmh": 19.8,
    "sprint_threshold_kmh": 25.3,
    "zone_edges_kmh": {
      "walk": 7.0,
      "jog": 15.0,
      "run": 19.8,
      "hsr": 25.3
    },
    "adapter_source": "stub",
    "adapter_runtime_s": 0.13,
    "detections_count": 74,
    "player_stats_count": 9,
    "adapter_metrics": {
      "sources": {
        "minutes_played": {
          "pipeline": 8
        },
        "avg_position": {
          "pipeline": 8
        },
        "heatmap": {
          "pipeline": 8
        }
      },
      "speed_thresholds": {
        "preset": "gps_standard",
        "hsr_kmh": 19.8,
        "sprint_kmh": 25.3,
        "zone_edges_kmh": {
          "walk": 7.0,
          "jog": 15.0,
          "run": 19.8,
          "hsr": 25.3
        }
      },
      "heatmap_grid": "pipeline"
    }
  }
}
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token; 404 not found or not yours; `422` invalid parameters

### DELETE /api/videos/{video_id}

**Auth:** Bearer token

Owner only. Deletes the row (DB cascades player_match_stats + tracking_detections + per-video player
overrides + player tracks), the uploaded file, thumbnail, cv_outputs/video_<id>/, cached frames
(cv_outputs/frames/video_<id>/), tracking outputs (cv_outputs/track_<track_id>/) and this video's per-track
placeholder players.
Tags live on the match: if this was the match's last video AND the match has no other stats (e.g. legacy rows
without a video), your tags on that match are removed too. The match itself (date, teams, score/result) is
kept, as before. Allowed while processing: the background task notices the row is gone and stops.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `video_id` | path | integer | yes |  |

**Example**

```http
DELETE /api/videos/8
```

Response **204** (no body)

**Status codes:** `204`; errors: 401 missing/invalid/expired Bearer token; 404 not found or not yours; `422` invalid parameters

### GET /api/videos/{video_id}/heatmap

**Auth:** Bearer token

Per-player occupancy grids for one video. 409 (same body as /stats) until done.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `video_id` | path | integer | yes |  |
| `player_id` | query | integer or null | no |  |

**Example**

```http
GET /api/videos/6/heatmap?player_id=24
```

Response **200**:

```json
{
  "video_id": 6,
  "grid": {
    "cols": 21,
    "rows": 14,
    "x_axis": "pitch length (pitch_x, m)",
    "y_axis": "pitch width (pitch_y, m)",
    "layout": "counts[row][col], row 0 = pitch_y 0, col 0 = pitch_x 0",
    "source": "pipeline",
    "cell_unit": "seconds",
    "pitch_length_m": 105.0,
    "pitch_width_m": 68.0
  },
  "players": [
    {
      "player_id": 24,
      "name": "Unknown #1",
      "samples": 8,
      "avg_position": {
        "x": 76.7,
        "y": 48.2
      },
      "cols": 21,
      "rows": 14,
      "source": "pipeline",
      "cell_unit": "seconds",
      "counts": [
        [
          0.0,
          0.0,
          0.0,
          0.0,
          0.0,
          0.0,
          "... 15 more"
        ],
        [
          0.0,
          0.0,
          0.0,
          0.0,
          0.0,
          0.0,
          "... 15 more"
        ],
        "... 12 more"
      ],
      "intensity": [
        [
          0.0,
          0.0,
          0.0,
          0.0,
          0.0,
          0.0,
          "... 15 more"
        ],
        [
          0.0,
          0.0,
          0.0,
          0.0,
          0.0,
          0.0,
          "... 15 more"
        ],
        "... 12 more"
      ]
    }
  ]
}
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token; 404 not found or not yours; 409 not processed yet (same body as /stats); `422` invalid parameters

### PATCH /api/videos/{video_id}/players/{player_id}

**Auth:** Bearer token

Owner only. Set the player's jersey number FOR THIS VIDEO (0-99, or null = no number), e.g. to fix OCR.
Stored per video in video_player_overrides; the roster (players.jersey_number) and other videos are unchanged.
Returns the player's row in the GET /api/videos/{id}/stats shape.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `video_id` | path | integer | yes |  |
| `player_id` | path | integer | yes |  |

**Request body** (`application/json`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `jersey_number` | integer or null | yes | Required. Integer 0-99, or null = no number in this video |

**Example**

```http
PATCH /api/videos/6/players/24
{
  "jersey_number": 10
}
```

Response **200**:

```json
{
  "player_id": 24,
  "name": "Unknown #1",
  "top_speed_mph": 18.5,
  "distance_km": 0.001,
  "injury_risk": "Low",
  "avg_position": {
    "x": 76.7,
    "y": 48.2
  },
  "jersey_number": 10,
  "top_speed_kmh": 29.8,
  "minutes_played": 0.01,
  "visible_minutes": 0.01,
  "coverage_pct": 80.0,
  "distance_per_min": null,
  "hsr_distance_km": 0.0,
  "sprint_distance_km": 0.0,
  "hsr_count": 0,
  "sprint_count": 0,
  "high_intensity_efforts": 0,
  "accels": 0,
  "decels": 0,
  "speed_zones": {
    "walk": 0.0,
    "jog": 0.0,
    "run": 0.0,
    "hsr": 0.0,
    "sprint": 0.0
  },
  "heatmap": {
    "cols": 21,
    "rows": 14,
    "cells": [
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      "... 288 more"
    ],
    "samples": 8,
    "source": "pipeline",
    "cell_unit": "seconds",
    "pitch_length_m": 105.0,
    "pitch_width_m": 68.0
  },
  "speed_thresholds": {
    "preset": "gps_standard",
    "hsr_kmh": 19.8,
    "sprint_kmh": 25.3,
    "zone_edges_kmh": {
      "walk": 7.0,
      "jog": 15.0,
      "run": 19.8,
      "hsr": 25.3
    },
    "source": "pipeline"
  }
}
```

**Status codes:** `200`, `404`, `409`, `503`; errors: 401 missing/invalid/expired Bearer token; 404 video not found / not yours, or player not in this video; 409 video not processed yet (same body as /stats), or the jersey is already used by a teammate in this video; 422 jersey_number missing, not an integer 0-99 / null, or unknown field; 503 migration 007 not run yet

### GET /api/videos/{video_id}/stats

**Auth:** Bearer token

Same shape as /api/players/stats, for the stats produced from THIS video.
409 {"detail", "status", "stage", "progress", "error_message"} until status is done; [] if done with no rows.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `video_id` | path | integer | yes |  |
| `include` | query | string or null | no | 'metrics' adds metrics {key: value/null} + avg_position |
| `metrics` | query | string or null | no | Comma-separated metric keys (default: all) |

**Example**

```http
GET /api/videos/6/stats
```

Response **200**:

```json
[
  {
    "player_id": 24,
    "name": "Unknown #1",
    "top_speed_mph": 18.5,
    "distance_km": 0.001,
    "injury_risk": "Low",
    "avg_position": {
      "x": 76.7,
      "y": 48.2
    },
    "jersey_number": null,
    "top_speed_kmh": 29.8,
    "minutes_played": 0.01,
    "visible_minutes": 0.01,
    "coverage_pct": 80.0,
    "distance_per_min": null,
    "hsr_distance_km": 0.0,
    "sprint_distance_km": 0.0,
    "hsr_count": 0,
    "sprint_count": 0,
    "high_intensity_efforts": 0,
    "accels": 0,
    "decels": 0,
    "speed_zones": {
      "walk": 0.0,
      "jog": 0.0,
      "run": 0.0,
      "hsr": 0.0,
      "sprint": 0.0
    },
    "heatmap": {
      "cols": 21,
      "rows": 14,
      "cells": [
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        "... 288 more"
      ],
      "samples": 8,
      "source": "pipeline",
      "cell_unit": "seconds",
      "pitch_length_m": 105.0,
      "pitch_width_m": 68.0
    },
    "speed_thresholds": {
      "preset": "gps_standard",
      "hsr_kmh": 19.8,
      "sprint_kmh": 25.3,
      "zone_edges_kmh": {
        "walk": 7.0,
        "jog": 15.0,
        "run": 19.8,
        "hsr": 25.3
      },
      "source": "pipeline"
    }
  },
  {
    "player_id": 25,
    "name": "Unknown #2",
    "top_speed_mph": 22.0,
    "distance_km": 0.001,
    "injury_risk": "Medium",
    "avg_position": {
      "x": 67.9,
      "y": 47.4
    },
    "jersey_number": null,
    "top_speed_kmh": 35.4,
    "minutes_played": 0.01,
    "visible_minutes": 0.01,
    "coverage_pct": 70.0,
    "distance_per_min": null,
    "hsr_distance_km": 0.0,
    "sprint_distance_km": 0.0,
    "hsr_count": 0,
    "sprint_count": 0,
    "high_intensity_efforts": 0,
    "accels": 0,
    "decels": 0,
    "speed_zones": {
      "walk": 0.0,
      "jog": 0.0,
      "run": 0.0,
      "hsr": 0.0,
      "sprint": 0.0
    },
    "heatmap": {
      "cols": 21,
      "rows": 14,
      "cells": [
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        "... 288 more"
      ],
      "samples": 7,
      "source": "pipeline",
      "cell_unit": "seconds",
      "pitch_length_m": 105.0,
      "pitch_width_m": 68.0
    },
    "speed_thresholds": {
      "preset": "gps_standard",
      "hsr_kmh": 19.8,
      "sprint_kmh": 25.3,
      "zone_edges_kmh": {
        "walk": 7.0,
        "jog": 15.0,
        "run": 19.8,
        "hsr": 25.3
      },
      "source": "pipeline"
    }
  },
  "... 6 more"
]
```

**Status codes:** `200`, `409`; errors: 401 missing/invalid/expired Bearer token; 404 not found or not yours; 409 not processed yet / failed: {detail, status, stage, progress, error_message}; `422` invalid parameters

### POST /api/videos/{video_id}/tags

**Auth:** Bearer token

Add tags to the video's MATCH (creates new keys/values). Body {tags:[{key,value}]} or a bare list.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `video_id` | path | integer | yes |  |

**Request body** (`application/json`)

**Example**

```http
POST /api/videos/6/tags
{
  "tags": [
    {
      "key": "competition",
      "value": "League"
    }
  ]
}
```

Response **200**:

```json
{
  "id": 6,
  "video_id": 6,
  "match_id": 8,
  "title": "Derby first half",
  "file_name": "derby.mp4",
  "match_date": "2026-09-20",
  "home_team": "Eagles FC",
  "away_team": "Riverside",
  "status": "done",
  "stage": "done",
  "progress": 100,
  "error_message": null,
  "error": null,
  "created_at": "2026-10-03T03:55:09Z",
  "uploaded_at": "2026-10-03T03:55:09Z",
  "processed_at": "2026-10-03T03:55:09Z",
  "fps": 30.0,
  "duration_seconds": 1.0,
  "thumbnail_url": null,
  "source_url": "/api/videos/6/source?token=<JWT>",
  "match": {
    "match_id": 8,
    "match_date": "2026-09-20",
    "home_team": "Eagles FC",
    "away_team": "Riverside",
    "home_score": null,
    "away_score": null,
    "result": null
  },
  "result": null,
  "tags": [
    {
      "key": "competition",
      "value": "League"
    },
    {
      "key": "Weather",
      "value": "Windy"
    }
  ],
  "pipeline_meta": {
    "fps": 30.0,
    "frame_count": 30,
    "duration_s": 1.0,
    "resolution": [
      1920,
      1080
    ],
    "model": "stub",
    "device": "none",
    "calibration": null,
    "pipeline_version": "stub-1",
    "runtime_s": 0.0,
    "warnings": [
      "STUB: fake demo data generated by backend/pipeline.py",
      "STUB: clip length unknown; assumed 1 s"
    ],
    "speed_preset": "gps_standard",
    "hsr_threshold_kmh": 19.8,
    "sprint_threshold_kmh": 25.3,
    "zone_edges_kmh": {
      "walk": 7.0,
      "jog": 15.0,
      "run": 19.8,
      "hsr": 25.3
    },
    "adapter_source": "stub",
    "adapter_runtime_s": 0.13,
    "detections_count": 74,
    "player_stats_count": 9,
    "adapter_metrics": {
      "sources": {
        "minutes_played": {
          "pipeline": 8
        },
        "avg_position": {
          "pipeline": 8
        },
        "heatmap": {
          "pipeline": 8
        }
      },
      "speed_thresholds": {
        "preset": "gps_standard",
        "hsr_kmh": 19.8,
        "sprint_kmh": 25.3,
        "zone_edges_kmh": {
          "walk": 7.0,
          "jog": 15.0,
          "run": 19.8,
          "hsr": 25.3
        }
      },
      "heatmap_grid": "pipeline"
    }
  }
}
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token; 404 not found or not yours; 422 bad tag (empty / too long / ':' in key) or > 50 tags

### GET /api/videos/{video_id}/tags

**Auth:** Bearer token

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `video_id` | path | integer | yes |  |

**Example**

```http
GET /api/videos/6/tags
```

Response **200**:

```json
[
  {
    "key": "competition",
    "value": "League"
  },
  {
    "key": "Weather",
    "value": "Windy"
  }
]
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token; 404 not found or not yours; `422` invalid parameters

### PUT /api/videos/{video_id}/tags

**Auth:** Bearer token

Replace the full tag set of the video's match ([] clears it).

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `video_id` | path | integer | yes |  |

**Request body** (`application/json`)

**Example**

```http
PUT /api/videos/6/tags
{
  "tags": [
    {
      "key": "weather",
      "value": "Windy"
    },
    {
      "key": "competition",
      "value": "Cup"
    }
  ]
}
```

Response **200**:

```json
{
  "id": 6,
  "video_id": 6,
  "match_id": 8,
  "title": "Derby first half",
  "file_name": "derby.mp4",
  "match_date": "2026-09-20",
  "home_team": "Eagles FC",
  "away_team": "Riverside",
  "status": "done",
  "stage": "done",
  "progress": 100,
  "error_message": null,
  "error": null,
  "created_at": "2026-10-03T03:55:09Z",
  "uploaded_at": "2026-10-03T03:55:09Z",
  "processed_at": "2026-10-03T03:55:09Z",
  "fps": 30.0,
  "duration_seconds": 1.0,
  "thumbnail_url": null,
  "source_url": "/api/videos/6/source?token=<JWT>",
  "match": {
    "match_id": 8,
    "match_date": "2026-09-20",
    "home_team": "Eagles FC",
    "away_team": "Riverside",
    "home_score": null,
    "away_score": null,
    "result": null
  },
  "result": null,
  "tags": [
    {
      "key": "competition",
      "value": "Cup"
    },
    {
      "key": "Weather",
      "value": "Windy"
    }
  ],
  "pipeline_meta": {
    "fps": 30.0,
    "frame_count": 30,
    "duration_s": 1.0,
    "resolution": [
      1920,
      1080
    ],
    "model": "stub",
    "device": "none",
    "calibration": null,
    "pipeline_version": "stub-1",
    "runtime_s": 0.0,
    "warnings": [
      "STUB: fake demo data generated by backend/pipeline.py",
      "STUB: clip length unknown; assumed 1 s"
    ],
    "speed_preset": "gps_standard",
    "hsr_threshold_kmh": 19.8,
    "sprint_threshold_kmh": 25.3,
    "zone_edges_kmh": {
      "walk": 7.0,
      "jog": 15.0,
      "run": 19.8,
      "hsr": 25.3
    },
    "adapter_source": "stub",
    "adapter_runtime_s": 0.13,
    "detections_count": 74,
    "player_stats_count": 9,
    "adapter_metrics": {
      "sources": {
        "minutes_played": {
          "pipeline": 8
        },
        "avg_position": {
          "pipeline": 8
        },
        "heatmap": {
          "pipeline": 8
        }
      },
      "speed_thresholds": {
        "preset": "gps_standard",
        "hsr_kmh": 19.8,
        "sprint_kmh": 25.3,
        "zone_edges_kmh": {
          "walk": 7.0,
          "jog": 15.0,
          "run": 19.8,
          "hsr": 25.3
        }
      },
      "heatmap_grid": "pipeline"
    }
  }
}
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token; 404 not found or not yours; 422 bad tag (empty / too long / ':' in key) or > 50 tags

### DELETE /api/videos/{video_id}/tags

**Auth:** Bearer token

Remove key=value (or all values of key) from the video's match. Idempotent 204.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `video_id` | path | integer | yes |  |
| `key` | query | string | yes |  |
| `value` | query | string or null | no |  |

**Example**

```http
DELETE /api/videos/6/tags?key=competition&value=Cup
```

Response **204** (no body)

**Status codes:** `204`; errors: 401 missing/invalid/expired Bearer token; 404 not found or not yours; 422 key missing

### GET /api/videos/{video_id}/thumbnail

**Auth:** Bearer token; the thumbnail also accepts its own `?token=` from `thumbnail_url`

Auth: `Authorization: Bearer <access token>` OR the `?token=` embedded in `thumbnail_url`
(scoped to this one video, short-lived). Access tokens are NOT accepted in the query string.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `video_id` | path | integer | yes |  |
| `token` | query | string or null | no | Thumbnail token from thumbnail_url (for <img src>) |

**Example**

```http
GET /api/videos/6/thumbnail
```

Response **404** (the stub clip has no thumbnail; with ffmpeg/OpenCV and a real clip this is `200 image/jpeg`):

```json
{
  "detail": "Thumbnail not found"
}
```

**Status codes:** `200`, `404`; errors: 401 no Bearer token and no valid ?token=; 404 no thumbnail / not yours; `422` invalid parameters

## Matches

### GET /api/matches

**Auth:** Bearer token

Matches where either team belongs to you, newest first, with your video count, score/result and tags.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `tag` | query | array | no | Filter key:value, repeatable: same key = OR, different keys = AND |

**Example**

```http
GET /api/matches
```

Response **200**:

```json
[
  {
    "match_id": 7,
    "match_date": "2026-10-03",
    "home_team": "Capstone FC",
    "away_team": "Harbor City",
    "home_team_id": 1,
    "away_team_id": 3,
    "video_count": 0,
    "home_score": null,
    "away_score": null,
    "our_side": "home",
    "our_team": "Capstone FC",
    "opponent": "Harbor City",
    "result": null,
    "tags": []
  },
  {
    "match_id": 2,
    "match_date": "2026-09-26",
    "home_team": "Rival United",
    "away_team": "Capstone FC",
    "home_team_id": 2,
    "away_team_id": 1,
    "video_count": 0,
    "home_score": 0,
    "away_score": 1,
    "our_side": "away",
    "our_team": "Capstone FC",
    "opponent": "Rival United",
    "result": "W",
    "tags": [
      {
        "key": "Pitch",
        "value": "Turf"
      },
      {
        "key": "Weather",
        "value": "Rainy"
      }
    ]
  },
  "... 6 more"
]
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token; `422` invalid parameters

### GET /api/matches/{match_id}

**Auth:** Bearer token

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `match_id` | path | integer | yes |  |

**Example**

```http
GET /api/matches/8
```

Response **200**:

```json
{
  "match_id": 8,
  "match_date": "2026-09-20",
  "home_team": "Eagles FC",
  "away_team": "Riverside",
  "home_team_id": 5,
  "away_team_id": 6,
  "video_count": 1,
  "home_score": 2,
  "away_score": 1,
  "our_side": "home",
  "our_team": "Eagles FC",
  "opponent": "Riverside",
  "result": "W",
  "tags": [
    {
      "key": "Weather",
      "value": "Windy"
    }
  ]
}
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token; 404 not your match; `422` invalid parameters

### PATCH /api/matches/{match_id}

**Auth:** Bearer token

Set score / our_side / result. Scores go in pairs (both ints or both null). With scores, result is derived.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `match_id` | path | integer | yes |  |

**Request body** (`application/json`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `home_score` | integer or null | no |  |
| `away_score` | integer or null | no |  |
| `our_side` | string or null | no |  |
| `result` | string or null | no |  |

**Example**

```http
PATCH /api/matches/8
{
  "home_score": 2,
  "away_score": 1
}
```

Response **200**:

```json
{
  "match_id": 8,
  "match_date": "2026-09-20",
  "home_team": "Eagles FC",
  "away_team": "Riverside",
  "home_team_id": 5,
  "away_team_id": 6,
  "video_count": 1,
  "home_score": 2,
  "away_score": 1,
  "our_side": "home",
  "our_team": "Eagles FC",
  "opponent": "Riverside",
  "result": "W",
  "tags": [
    {
      "key": "Weather",
      "value": "Windy"
    }
  ]
}
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token; 404 not your match; 422 nothing to change, scores not paired, bad our_side, result contradicts score

### POST /api/matches/{match_id}/tags

**Auth:** Bearer token

Add tags (keys/values are created if new). Body {tags:[{key,value}]} or a bare list. -> full tag set.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `match_id` | path | integer | yes |  |

**Request body** (`application/json`)

**Example**

```http
POST /api/matches/8/tags
{
  "tags": [
    {
      "key": "pitch",
      "value": "Turf"
    }
  ]
}
```

Response **200**:

```json
[
  {
    "key": "Pitch",
    "value": "Turf"
  },
  {
    "key": "Weather",
    "value": "Windy"
  }
]
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token; 404 not found or not yours; 422 bad tag (empty / too long / ':' in key) or > 50 tags

### GET /api/matches/{match_id}/tags

**Auth:** Bearer token

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `match_id` | path | integer | yes |  |

**Example**

```http
GET /api/matches/8/tags
```

Response **200**:

```json
[
  {
    "key": "Pitch",
    "value": "Turf"
  },
  {
    "key": "Weather",
    "value": "Windy"
  }
]
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token; 404 not found or not yours; `422` invalid parameters

### PUT /api/matches/{match_id}/tags

**Auth:** Bearer token

Replace the full tag set ([] clears it). -> full tag set.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `match_id` | path | integer | yes |  |

**Request body** (`application/json`)

**Example**

```http
PUT /api/matches/8/tags
{
  "tags": [
    {
      "key": "weather",
      "value": "Windy"
    },
    {
      "key": "pitch",
      "value": "Grass"
    }
  ]
}
```

Response **200**:

```json
[
  {
    "key": "Pitch",
    "value": "Grass"
  },
  {
    "key": "Weather",
    "value": "Windy"
  }
]
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token; 404 not found or not yours; 422 bad tag (empty / too long / ':' in key) or > 50 tags

### DELETE /api/matches/{match_id}/tags

**Auth:** Bearer token

Remove key=value (or every value of `key` if value is omitted). Idempotent: 204 even if absent.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `match_id` | path | integer | yes |  |
| `key` | query | string | yes |  |
| `value` | query | string or null | no |  |

**Example**

```http
DELETE /api/matches/8/tags?key=pitch
```

Response **204** (no body)

**Status codes:** `204`; errors: 401 missing/invalid/expired Bearer token; 404 not found or not yours; 422 key missing

## Tags

### GET /api/tags

**Auth:** Bearer token

[{key, values:[{value, count}]}], keys A-Z, values by count desc. count = number of your matches tagged.
Keys with no values yet are included with values: [].

**Example**

```http
GET /api/tags
```

Response **200**:

```json
[
  {
    "key": "competition",
    "values": [
      {
        "value": "Cup",
        "count": 0
      },
      {
        "value": "League",
        "count": 0
      }
    ]
  },
  {
    "key": "Pitch",
    "values": [
      {
        "value": "Grass",
        "count": 3
      },
      {
        "value": "Turf",
        "count": 3
      }
    ]
  },
  "... 1 more"
]
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token

### GET /api/tags/keys

**Auth:** Bearer token

[{key, value_count, match_count}] (match_count = matches with any value of that key).

**Example**

```http
GET /api/tags/keys
```

Response **200**:

```json
[
  {
    "key": "Pitch",
    "value_count": 2,
    "match_count": 6
  },
  {
    "key": "Weather",
    "value_count": 3,
    "match_count": 7
  },
  "... 1 more"
]
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token

### GET /api/tags/values

**Auth:** Bearer token

[{key, value, count}] sorted by count desc. Unknown key -> [].

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `key` | query | string or null | no | Only values of this key |
| `q` | query | string or null | no | Case-insensitive prefix filter |

**Example**

```http
GET /api/tags/values?key=weather
```

Response **200**:

```json
[
  {
    "key": "Weather",
    "value": "Rainy",
    "count": 3
  },
  {
    "key": "Weather",
    "value": "Sunny",
    "count": 3
  },
  "... 1 more"
]
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token; `422` invalid parameters

## Players & metrics

### GET /api/metrics

**Auth:** none (public)

Public registry of per-player metrics (label, unit, aggregation rule, availability ready|soon, ...).

**Example**

```http
GET /api/metrics
```

Response **200**:

```json
[
  {
    "key": "distance_km",
    "label": "Total distance",
    "unit": "km",
    "category": "physical",
    "value_type": "float",
    "aggregation": "sum",
    "decimals": 2,
    "higher_is_better": true,
    "requires_calibration": true,
    "is_estimate": true,
    "availability": "ready",
    "storage": "column",
    "description": "Distance covered while tracked (smoothed). Estimated from video.",
    "sort_order": 10
  },
  {
    "key": "top_speed_mph",
    "label": "Top speed (max sustained)",
    "unit": "mph",
    "category": "physical",
    "value_type": "float",
    "aggregation": "max",
    "decimals": 1,
    "higher_is_better": true,
    "requires_calibration": true,
    "is_estimate": true,
    "availability": "ready",
    "storage": "column",
    "description": "Max sustained (~1 s rolling) speed. Estimated from video.",
    "sort_order": 11
  },
  "... 19 more"
]
```

**Status codes:** `200`

### GET /api/players/stats

**Auth:** none (public)

Per-player aggregate across player_match_stats:
max top speed, total distance, worst injury risk. Players with no stats are excluded.
Unchanged shape unless ?include=metrics.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `match_id` | query | integer or null | no | Only include stats from this match |
| `team_id` | query | integer or null | no | Only include players on this team |
| `include` | query | string or null | no | 'metrics' adds metrics {key: value/null} + avg_position |
| `metrics` | query | string or null | no | Comma-separated metric keys (default: all) |

**Example**

```http
GET /api/players/stats?include=metrics&metrics=sprint_count,hsr_distance_km
```

Response **200**:

```json
[
  {
    "player_id": 1,
    "name": "Ivan Horvat",
    "top_speed_mph": 14.6,
    "distance_km": 2.3,
    "injury_risk": "Low",
    "metrics": {
      "sprint_count": 17,
      "hsr_distance_km": 0.23
    },
    "avg_position": {
      "x": 8.0,
      "y": 34.6
    },
    "jersey_number": 1,
    "top_speed_kmh": 23.5,
    "minutes_played": 60.0,
    "visible_minutes": 55.63,
    "coverage_pct": 93.0,
    "distance_per_min": 41.0,
    "hsr_distance_km": 0.23,
    "sprint_distance_km": 0.1,
    "hsr_count": 10,
    "sprint_count": 17,
    "high_intensity_efforts": 27,
    "accels": 14,
    "decels": 18,
    "speed_zones": {
      "walk": 0.73,
      "jog": 0.83,
      "run": 0.42,
      "hsr": 0.22,
      "sprint": 0.11
    },
    "heatmap": {
      "cols": 12,
      "rows": 8,
      "cells": [
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        "... 90 more"
      ],
      "samples": 300,
      "source": "backend",
      "cell_unit": "samples",
      "pitch_length_m": 105.0,
      "pitch_width_m": 68.0
    }
  },
  {
    "player_id": 4,
    "name": "Tomas Novak",
    "top_speed_mph": 17.9,
    "distance_km": 23.3,
    "injury_risk": "Low",
    "metrics": {
      "sprint_count": 58,
      "hsr_distance_km": 2.6
    },
    "avg_position": {
      "x": 27.7,
      "y": 30.2
    },
    "jersey_number": 4,
    "top_speed_kmh": 28.8,
    "minutes_played": 300.0,
    "visible_minutes": 269.04,
    "coverage_pct": 90.0,
    "distance_per_min": 87.0,
    "hsr_distance_km": 2.6,
    "sprint_distance_km": 0.92,
    "hsr_count": 100,
    "sprint_count": 58,
    "high_intensity_efforts": 158,
    "accels": 34,
    "decels": 44,
    "speed_zones": {
      "walk": 7.46,
      "jog": 8.68,
      "run": 4.32,
      "hsr": 2.12,
      "sprint": 0.72
    },
    "heatmap": {
      "cols": 21,
      "rows": 14,
      "cells": [
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        "... 288 more"
      ],
      "samples": 1200,
      "source": "pipeline",
      "cell_unit": "seconds",
      "pitch_length_m": 105.0,
      "pitch_width_m": 68.0
    }
  },
  "... 15 more"
]
```

**Status codes:** `200`; `422` invalid parameters

### GET /api/players/{player_id}

**Auth:** none (public)

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `player_id` | path | integer | yes |  |

**Example**

```http
GET /api/players/24
```

Response **200**:

```json
{
  "player_id": 24,
  "team_id": 5,
  "first_name": "Unknown",
  "last_name": "#1",
  "jersey_number": null,
  "position": "Unassigned",
  "dominant_foot": null
}
```

**Status codes:** `200`; errors: 404 player not found; `422` invalid parameters

### GET /api/players/{player_id}/heatmap

**Auth:** Bearer token

The player's grid summed over your videos (optionally one video / match).

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `player_id` | path | integer | yes |  |
| `video_id` | query | integer or null | no |  |
| `match_id` | query | integer or null | no |  |

**Example**

```http
GET /api/players/24/heatmap
```

Response **200**:

```json
{
  "player_id": 24,
  "name": "Unknown #1",
  "videos": 1,
  "videos_skipped": 0,
  "grid": {
    "cols": 21,
    "rows": 14,
    "x_axis": "pitch length (pitch_x, m)",
    "y_axis": "pitch width (pitch_y, m)",
    "layout": "counts[row][col], row 0 = pitch_y 0, col 0 = pitch_x 0",
    "source": "pipeline",
    "cell_unit": "seconds",
    "pitch_length_m": 105.0,
    "pitch_width_m": 68.0
  },
  "samples": 8,
  "avg_position": {
    "x": 76.7,
    "y": 48.2
  },
  "counts": [
    [
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      "... 15 more"
    ],
    [
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      "... 15 more"
    ],
    "... 12 more"
  ],
  "intensity": [
    [
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      "... 15 more"
    ],
    [
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      0.0,
      "... 15 more"
    ],
    "... 12 more"
  ]
}
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token; 404 not your player; `422` invalid parameters

### GET /api/players/{player_id}/metrics

**Auth:** Bearer token

Per-video history (one entry per stats row, oldest first) + totals. Your players only (404 otherwise).

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `player_id` | path | integer | yes |  |
| `metrics` | query | string or null | no | Comma-separated metric keys (default: all) |

**Example**

```http
GET /api/players/24/metrics?metrics=distance_km,sprint_count
```

Response **200**:

```json
{
  "player_id": 24,
  "name": "Unknown #1",
  "team_id": 5,
  "series": [
    {
      "video_id": 6,
      "video_title": "Derby first half",
      "match_id": 8,
      "match_date": "2026-09-20",
      "home_team": "Eagles FC",
      "away_team": "Riverside",
      "result": "W",
      "top_speed_mph": null,
      "distance_km": 0.0,
      "injury_risk": "Low",
      "metrics": {
        "distance_km": 0.0,
        "sprint_count": 0
      },
      "avg_position": {
        "x": 76.7,
        "y": 48.2
      }
    }
  ],
  "totals": {
    "appearances": 1,
    "top_speed_mph": null,
    "distance_km": 0.0,
    "injury_risk": "Low",
    "metrics": {
      "distance_km": 0.0,
      "sprint_count": 0
    },
    "avg_position": {
      "x": 76.7,
      "y": 48.2
    }
  }
}
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token; 404 not your player; `422` invalid parameters

## Insights

### GET /api/insights

**Auth:** Bearer token

Same response as /api/insights/tags (frontend contract name).

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `tag_key` | query | string or null | no | Tag key (alias: key) |
| `key` | query | string or null | no |  |
| `player_id` | query | integer or null | no |  |
| `team_id` | query | integer or null | no |  |

**Example**

```http
GET /api/insights?tag_key=weather
```

Response **200**:

```json
{
  "key": "weather",
  "filters": {
    "player_id": null,
    "team_id": null
  },
  "scope": "our_team",
  "definitions": {
    "avg_workload": "avg_workload = mean workload band per player appearance from the pipeline's workload-based injury-risk (Low=1, Medium=2, High=3; range 1-3). Workload indicat...",
    "unit_of_analysis": "match; per-match value = mean over players in scope",
    "next_match": "your next match chronologically after each tagged match (deduplicated)",
    "low_sample": "true when fewer than 3 matches have data"
  },
  "baseline": {
    "matches": 8,
    "matches_with_data": 7,
    "metrics": {
      "distance_km": 3.002,
      "top_speed_mph": 19.6,
      "sprint_count": 9.2,
      "hsr_distance_km": 0.349,
      "sprint_distance_km": 0.114,
      "distance_per_min": 66.4,
      "workload": 1.664
    },
    "metric_n": {
      "distance_km": 7,
      "top_speed_mph": 7,
      "sprint_count": 7,
      "hsr_distance_km": 7,
      "sprint_distance_km": 7,
      "distance_per_min": 6,
      "workload": 7
    },
    "injury_risk": {
      "Low": 15,
      "Medium": 13,
      "High": 4
    },
    "wdl": {
      "w": 5,
      "d": 1,
      "l": 1,
      "unknown": 1
    },
    "match_ids": [
      3,
      4,
      5,
      1,
      6,
      8,
      "... 2 more"
    ],
    "avg_distance_km": 3.002,
    "avg_top_speed_mph": 19.6,
    "avg_sprints": 9.2,
    "avg_hsr_distance_km": 0.349,
    "avg_workload": 1.664,
    "workload": {
      "low": 15,
      "medium": 13,
      "high": 4
    }
  },
  "groups": [
    {
      "value": "Rainy",
      "matches": 3,
      "matches_with_data": 3,
      "low_sample": false,
      "avg_distance_km": 3.003,
      "avg_top_speed_mph": 19.1,
      "avg_sprints": 10.6,
      "avg_hsr_distance_km": 0.354,
      "avg_sprint_distance_km": 0.121,
      "avg_distance_per_min": 57.5,
      "avg_workload": 1.917,
      "metrics": {
        "distance_km": 3.003,
        "top_speed_mph": 19.1,
        "sprint_count": 10.6,
        "hsr_distance_km": 0.354,
        "sprint_distance_km": 0.121,
        "distance_per_min": 57.5,
        "workload": 1.917
      },
      "metric_n": {
        "distance_km": 3,
        "top_speed_mph": 3,
        "sprint_count": 3,
        "hsr_distance_km": 3,
        "sprint_distance_km": 3,
        "distance_per_min": 3,
        "workload": 3
      },
      "delta_vs_baseline": {
        "distance_km": 0.001,
        "top_speed_mph": -0.5,
        "sprint_count": 1.4,
        "hsr_distance_km": 0.005,
        "sprint_distance_km": 0.007,
        "distance_per_min": -8.9,
        "workload": 0.253
      },
      "change_pct_vs_baseline": {
        "distance_km": 0.0,
        "top_speed_mph": -2.6,
        "sprint_count": 15.2,
        "hsr_distance_km": 1.4,
        "sprint_distance_km": 6.1,
        "distance_per_min": -13.4,
        "workload": 15.2
      },
      "injury_risk": {
        "Low": 4,
        "Medium": 4,
        "High": 3
      },
      "workload": {
        "low": 4,
        "medium": 4,
        "high": 3
      },
      "wdl": {
        "w": 2,
        "d": 0,
        "l": 1,
        "unknown": 0
      },
      "match_ids": [
        3,
        5,
        2
      ],
      "next_match": {
        "matches": 3,
        "matches_with_data": 2,
        "low_sample": true,
        "metrics": {
          "distance_km": 3.877,
          "top_speed_mph": 20.1,
          "sprint_count": 11.2,
          "hsr_distance_km": 0.461,
          "sprint_distance_km": 0.139,
          "distance_per_min": 73.1,
          "workload": 1.45
        },
        "metric_n": {
          "distance_km": 2,
          "top_speed_mph": 2,
          "sprint_count": 2,
          "hsr_distance_km": 2,
          "sprint_distance_km": 2,
          "distance_per_min": 2,
          "workload": 2
        },
        "injury_risk": {
          "Low": 5,
          "Medium": 4,
          "High": 0
        },
        "wdl": {
          "w": 1,
          "d": 1,
          "l": 0,
          "unknown": 1
        },
        "match_ids": [
          4,
          1,
          7
        ],
        "delta": {
          "distance_km": 0.875,
          "top_speed_mph": 0.5,
          "sprint_count": 2.0,
          "hsr_distance_km": 0.112,
          "sprint_distance_km": 0.025,
          "distance_per_min": 6.7,
          "workload": -0.214
        },
        "change_pct": {
          "distance_km": 29.1,
          "top_speed_mph": 2.6,
          "sprint_count": 21.7,
          "hsr_distance_km": 32.1,
          "sprint_distance_km": 21.9,
          "distance_per_min": 10.1,
          "workload": -12.9
        },
        "pairs": 2
      }
    },
    {
      "value": "Sunny",
      "matches": 3,
      "matches_with_data": 3,
      "low_sample": false,
      "avg_distance_km": 4.002,
      "avg_top_speed_mph": 20.3,
      "avg_sprints": 11.0,
      "avg_hsr_distance_km": 0.46,
      "avg_sprint_distance_km": 0.146,
      "avg_distance_per_min": 75.2,
      "avg_workload": 1.383,
      "metrics": {
        "distance_km": 4.002,
        "top_speed_mph": 20.3,
        "sprint_count": 11.0,
        "hsr_distance_km": 0.46,
        "sprint_distance_km": 0.146,
        "distance_per_min": 75.2,
        "workload": 1.383
      },
      "metric_n": {
        "distance_km": 3,
        "top_speed_mph": 3,
        "sprint_count": 3,
        "hsr_distance_km": 3,
        "sprint_distance_km": 3,
        "distance_per_min": 3,
        "workload": 3
      },
      "delta_vs_baseline": {
        "distance_km": 1.0,
        "top_speed_mph": 0.7,
        "sprint_count": 1.8,
        "hsr_distance_km": 0.111,
        "sprint_distance_km": 0.032,
        "distance_per_min": 8.8,
        "workload": -0.281
      },
      "change_pct_vs_baseline": {
        "distance_km": 33.3,
        "top_speed_mph": 3.6,
        "sprint_count": 19.6,
        "hsr_distance_km": 31.8,
        "sprint_distance_km": 28.1,
        "distance_per_min": 13.3,
        "workload": -16.9
      },
      "injury_risk": {
        "Low": 8,
        "Medium": 5,
        "High": 0
      },
      "workload": {
        "low": 8,
        "medium": 5,
        "high": 0
      },
      "wdl": {
        "w": 2,
        "d": 1,
        "l": 0,
        "unknown": 0
      },
      "match_ids": [
        4,
        1,
        6
      ],
      "next_match": {
        "matches": 3,
        "matches_with_data": 3,
        "low_sample": false,
        "metrics": {
          "distance_km": 2.425,
          "top_speed_mph": 19.3,
          "sprint_count": 6.8,
          "hsr_distance_km": 0.286,
          "sprint_distance_km": 0.097,
          "distance_per_min": 68.2,
          "workload": 1.75
        },
        "metric_n": {
          "distance_km": 3,
          "top_speed_mph": 3,
          "sprint_count": 3,
          "hsr_distance_km": 3,
          "sprint_distance_km": 3,
          "distance_per_min": 2,
          "workload": 3
        },
        "injury_risk": {
          "Low": 7,
          "Medium": 6,
          "High": 3
        },
        "wdl": {
          "w": 2,
          "d": 0,
          "l": 1,
          "unknown": 0
        },
        "match_ids": [
          5,
          6,
          8
        ],
        "delta": {
          "distance_km": -0.577,
          "top_speed_mph": -0.3,
          "sprint_count": -2.4,
          "hsr_distance_km": -0.063,
          "sprint_distance_km": -0.017,
          "distance_per_min": 1.8,
          "workload": 0.086
        },
        "change_pct": {
          "distance_km": -19.2,
          "top_speed_mph": -1.5,
          "sprint_count": -26.1,
          "hsr_distance_km": -18.1,
          "sprint_distance_km": -14.9,
          "distance_per_min": 2.7,
          "workload": 5.2
        },
        "pairs": 3
      }
    },
    "... 1 more"
  ],
  "next_match_effect": [
    {
      "value": "Rainy",
      "metric": "distance",
      "metric_key": "distance_km",
      "change_pct": 29.1,
      "delta": 0.875,
      "next": 3.877,
      "next_avg": 3.877,
      "baseline": 3.002,
      "n": 2,
      "pairs": 2,
      "low_sample": true
    },
    {
      "value": "Rainy",
      "metric": "speed",
      "metric_key": "top_speed_mph",
      "change_pct": 2.6,
      "delta": 0.5,
      "next": 20.1,
      "next_avg": 20.1,
      "baseline": 19.6,
      "n": 2,
      "pairs": 2,
      "low_sample": true
    },
    "... 13 more"
  ]
}
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token; 404 player_id / team_id not yours; 422 tag_key/key missing

### GET /api/insights/tags

**Auth:** Bearer token

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `key` | query | string | yes | Tag key, e.g. weather |
| `player_id` | query | integer or null | no |  |
| `team_id` | query | integer or null | no |  |

**Example**

```http
GET /api/insights/tags?key=weather
```

Response **200**:

```json
{
  "key": "weather",
  "filters": {
    "player_id": null,
    "team_id": null
  },
  "scope": "our_team",
  "definitions": {
    "avg_workload": "avg_workload = mean workload band per player appearance from the pipeline's workload-based injury-risk (Low=1, Medium=2, High=3; range 1-3). Workload indicat...",
    "unit_of_analysis": "match; per-match value = mean over players in scope",
    "next_match": "your next match chronologically after each tagged match (deduplicated)",
    "low_sample": "true when fewer than 3 matches have data"
  },
  "baseline": {
    "matches": 8,
    "matches_with_data": 7,
    "metrics": {
      "distance_km": 3.002,
      "top_speed_mph": 19.6,
      "sprint_count": 9.2,
      "hsr_distance_km": 0.349,
      "sprint_distance_km": 0.114,
      "distance_per_min": 66.4,
      "workload": 1.664
    },
    "metric_n": {
      "distance_km": 7,
      "top_speed_mph": 7,
      "sprint_count": 7,
      "hsr_distance_km": 7,
      "sprint_distance_km": 7,
      "distance_per_min": 6,
      "workload": 7
    },
    "injury_risk": {
      "Low": 15,
      "Medium": 13,
      "High": 4
    },
    "wdl": {
      "w": 5,
      "d": 1,
      "l": 1,
      "unknown": 1
    },
    "match_ids": [
      3,
      4,
      5,
      1,
      6,
      8,
      "... 2 more"
    ],
    "avg_distance_km": 3.002,
    "avg_top_speed_mph": 19.6,
    "avg_sprints": 9.2,
    "avg_hsr_distance_km": 0.349,
    "avg_workload": 1.664,
    "workload": {
      "low": 15,
      "medium": 13,
      "high": 4
    }
  },
  "groups": [
    {
      "value": "Rainy",
      "matches": 3,
      "matches_with_data": 3,
      "low_sample": false,
      "avg_distance_km": 3.003,
      "avg_top_speed_mph": 19.1,
      "avg_sprints": 10.6,
      "avg_hsr_distance_km": 0.354,
      "avg_sprint_distance_km": 0.121,
      "avg_distance_per_min": 57.5,
      "avg_workload": 1.917,
      "metrics": {
        "distance_km": 3.003,
        "top_speed_mph": 19.1,
        "sprint_count": 10.6,
        "hsr_distance_km": 0.354,
        "sprint_distance_km": 0.121,
        "distance_per_min": 57.5,
        "workload": 1.917
      },
      "metric_n": {
        "distance_km": 3,
        "top_speed_mph": 3,
        "sprint_count": 3,
        "hsr_distance_km": 3,
        "sprint_distance_km": 3,
        "distance_per_min": 3,
        "workload": 3
      },
      "delta_vs_baseline": {
        "distance_km": 0.001,
        "top_speed_mph": -0.5,
        "sprint_count": 1.4,
        "hsr_distance_km": 0.005,
        "sprint_distance_km": 0.007,
        "distance_per_min": -8.9,
        "workload": 0.253
      },
      "change_pct_vs_baseline": {
        "distance_km": 0.0,
        "top_speed_mph": -2.6,
        "sprint_count": 15.2,
        "hsr_distance_km": 1.4,
        "sprint_distance_km": 6.1,
        "distance_per_min": -13.4,
        "workload": 15.2
      },
      "injury_risk": {
        "Low": 4,
        "Medium": 4,
        "High": 3
      },
      "workload": {
        "low": 4,
        "medium": 4,
        "high": 3
      },
      "wdl": {
        "w": 2,
        "d": 0,
        "l": 1,
        "unknown": 0
      },
      "match_ids": [
        3,
        5,
        2
      ],
      "next_match": {
        "matches": 3,
        "matches_with_data": 2,
        "low_sample": true,
        "metrics": {
          "distance_km": 3.877,
          "top_speed_mph": 20.1,
          "sprint_count": 11.2,
          "hsr_distance_km": 0.461,
          "sprint_distance_km": 0.139,
          "distance_per_min": 73.1,
          "workload": 1.45
        },
        "metric_n": {
          "distance_km": 2,
          "top_speed_mph": 2,
          "sprint_count": 2,
          "hsr_distance_km": 2,
          "sprint_distance_km": 2,
          "distance_per_min": 2,
          "workload": 2
        },
        "injury_risk": {
          "Low": 5,
          "Medium": 4,
          "High": 0
        },
        "wdl": {
          "w": 1,
          "d": 1,
          "l": 0,
          "unknown": 1
        },
        "match_ids": [
          4,
          1,
          7
        ],
        "delta": {
          "distance_km": 0.875,
          "top_speed_mph": 0.5,
          "sprint_count": 2.0,
          "hsr_distance_km": 0.112,
          "sprint_distance_km": 0.025,
          "distance_per_min": 6.7,
          "workload": -0.214
        },
        "change_pct": {
          "distance_km": 29.1,
          "top_speed_mph": 2.6,
          "sprint_count": 21.7,
          "hsr_distance_km": 32.1,
          "sprint_distance_km": 21.9,
          "distance_per_min": 10.1,
          "workload": -12.9
        },
        "pairs": 2
      }
    },
    {
      "value": "Sunny",
      "matches": 3,
      "matches_with_data": 3,
      "low_sample": false,
      "avg_distance_km": 4.002,
      "avg_top_speed_mph": 20.3,
      "avg_sprints": 11.0,
      "avg_hsr_distance_km": 0.46,
      "avg_sprint_distance_km": 0.146,
      "avg_distance_per_min": 75.2,
      "avg_workload": 1.383,
      "metrics": {
        "distance_km": 4.002,
        "top_speed_mph": 20.3,
        "sprint_count": 11.0,
        "hsr_distance_km": 0.46,
        "sprint_distance_km": 0.146,
        "distance_per_min": 75.2,
        "workload": 1.383
      },
      "metric_n": {
        "distance_km": 3,
        "top_speed_mph": 3,
        "sprint_count": 3,
        "hsr_distance_km": 3,
        "sprint_distance_km": 3,
        "distance_per_min": 3,
        "workload": 3
      },
      "delta_vs_baseline": {
        "distance_km": 1.0,
        "top_speed_mph": 0.7,
        "sprint_count": 1.8,
        "hsr_distance_km": 0.111,
        "sprint_distance_km": 0.032,
        "distance_per_min": 8.8,
        "workload": -0.281
      },
      "change_pct_vs_baseline": {
        "distance_km": 33.3,
        "top_speed_mph": 3.6,
        "sprint_count": 19.6,
        "hsr_distance_km": 31.8,
        "sprint_distance_km": 28.1,
        "distance_per_min": 13.3,
        "workload": -16.9
      },
      "injury_risk": {
        "Low": 8,
        "Medium": 5,
        "High": 0
      },
      "workload": {
        "low": 8,
        "medium": 5,
        "high": 0
      },
      "wdl": {
        "w": 2,
        "d": 1,
        "l": 0,
        "unknown": 0
      },
      "match_ids": [
        4,
        1,
        6
      ],
      "next_match": {
        "matches": 3,
        "matches_with_data": 3,
        "low_sample": false,
        "metrics": {
          "distance_km": 2.425,
          "top_speed_mph": 19.3,
          "sprint_count": 6.8,
          "hsr_distance_km": 0.286,
          "sprint_distance_km": 0.097,
          "distance_per_min": 68.2,
          "workload": 1.75
        },
        "metric_n": {
          "distance_km": 3,
          "top_speed_mph": 3,
          "sprint_count": 3,
          "hsr_distance_km": 3,
          "sprint_distance_km": 3,
          "distance_per_min": 2,
          "workload": 3
        },
        "injury_risk": {
          "Low": 7,
          "Medium": 6,
          "High": 3
        },
        "wdl": {
          "w": 2,
          "d": 0,
          "l": 1,
          "unknown": 0
        },
        "match_ids": [
          5,
          6,
          8
        ],
        "delta": {
          "distance_km": -0.577,
          "top_speed_mph": -0.3,
          "sprint_count": -2.4,
          "hsr_distance_km": -0.063,
          "sprint_distance_km": -0.017,
          "distance_per_min": 1.8,
          "workload": 0.086
        },
        "change_pct": {
          "distance_km": -19.2,
          "top_speed_mph": -1.5,
          "sprint_count": -26.1,
          "hsr_distance_km": -18.1,
          "sprint_distance_km": -14.9,
          "distance_per_min": 2.7,
          "workload": 5.2
        },
        "pairs": 3
      }
    },
    "... 1 more"
  ],
  "next_match_effect": [
    {
      "value": "Rainy",
      "metric": "distance",
      "metric_key": "distance_km",
      "change_pct": 29.1,
      "delta": 0.875,
      "next": 3.877,
      "next_avg": 3.877,
      "baseline": 3.002,
      "n": 2,
      "pairs": 2,
      "low_sample": true
    },
    {
      "value": "Rainy",
      "metric": "speed",
      "metric_key": "top_speed_mph",
      "change_pct": 2.6,
      "delta": 0.5,
      "next": 20.1,
      "next_avg": 20.1,
      "baseline": 19.6,
      "n": 2,
      "pairs": 2,
      "low_sample": true
    },
    "... 13 more"
  ]
}
```

**Status codes:** `200`; errors: 401 missing/invalid/expired Bearer token; 404 player_id / team_id not yours; 422 key missing

## Player tracking

### GET /api/videos/{video_id}/source

**Auth:** Bearer token; or the short-lived `?token=` from `source_url` (this video only). Also answers `HEAD`

The original uploaded file (for the live canvas overlay). Auth: Bearer, or the `?token=` in `source_url`
(scoped to this video, short-lived; re-fetch the video for a fresh URL). Full HTTP Range support (206/416,
Accept-Ranges, ETag, If-Range) and HEAD. Any processing status.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `video_id` | path | integer | yes |  |
| `token` | query | string or null | no | Media token from source_url (for <video src>) |

**Example**

```http
GET /api/videos/7/source?token=<JWT>
Range: bytes=0-1023
```

Response **206**:

```json
<video/mp4 1024 bytes>
```

**Status codes:** `200`, `206`, `401`, `404`, `416`; errors: 401 no Bearer token and no valid ?token= (expired, forged, other video); 404 video not found / not yours / file missing; 416 Range not satisfiable (Content-Range: bytes */<size>); `422` invalid parameters

### GET /api/videos/{video_id}/frame

**Auth:** Bearer token; or the short-lived `?token=` from `frame_url` (this video only)

JPEG of one frame in source-video resolution (pick-mode still, crop thumbnails). Auth: Bearer, or the
`?token=` in `frame_url` (scoped to this video, short-lived). Cached per (video, frame) with its detections.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `video_id` | path | integer | yes |  |
| `frame` | query | integer or null | no | 0-based frame index (default 0) |
| `t` | query | number or null | no | Seconds into the clip (instead of frame) |
| `token` | query | string or null | no | Media token from frame_url (for <img src>) |

**Example**

```http
GET /api/videos/7/frame?frame=50
```

Response **200**:

```json
<image/jpeg 56286 bytes>
```

**Status codes:** `200`, `401`, `404`; errors: 401 no Bearer token and no valid ?token= (expired, forged, other video); 404 video not found / not yours; 422 both t and frame, or outside the clip; 409/502/503/504 as for /detections

### GET /api/videos/{video_id}/detections

**Auth:** Bearer token

People detected on one frame (pick mode). bbox = [x, y, w, h] normalised 0-1, top-left origin.
player_id = the app player when the processed video's own detections match the box, else null.
team 'A'|'B'|null; class player|goalkeeper|referee. frame_url = the matching JPEG (token in the URL).

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `video_id` | path | integer | yes |  |
| `frame` | query | integer or null | no | 0-based frame index (default 0) |
| `t` | query | number or null | no | Seconds into the clip (instead of frame) |

**Example**

```http
GET /api/videos/7/detections?frame=50
```

Response **200**:

```json
{
  "frame": 50,
  "t": 2.0,
  "width": 1280,
  "height": 720,
  "frame_url": "/api/videos/7/frame?frame=50&token=<JWT>",
  "source": "stub",
  "players": [
    {
      "player_id": null,
      "jersey_number": null,
      "team": null,
      "class": "referee",
      "bbox": [
        0.9566,
        0.6439,
        0.0367,
        0.154
      ],
      "conf": 0.741
    },
    {
      "player_id": null,
      "jersey_number": null,
      "team": "A",
      "class": "goalkeeper",
      "bbox": [
        0.2166,
        0.4385,
        0.0312,
        0.1218
      ],
      "conf": 0.794
    },
    "... 8 more"
  ]
}
```

**Status codes:** `200`, `404`, `502`, `503`; errors: 401 missing/invalid/expired Bearer token; 404 video not found / not yours; 422 both t and frame, or outside the clip; 409 the uploaded file is missing (real mode); 502 cv.detect_frame failed / bad output; 503 CV tracking modules not available (only with TRACK_PIPELINE_MODE=real); 504 cv.detect_frame timed out

### POST /api/videos/{video_id}/tracks

**Auth:** Bearer token

Start following one player through the clip (background; poll GET /api/tracks/{track_id}).
Body `{frame?|t?, bbox?, player_id?, jersey_number?, team?}`: needs bbox + frame/t, OR player_id, OR
jersey_number (team always optional). bbox = [x, y, w, h] normalised 0-1 on that frame. Returns 202 with the
full track object. One active (queued/processing) track per video: 409 `{detail, track_id, status, progress}`.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `video_id` | path | integer | yes |  |

**Request body** (`application/json`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `frame` | integer or null | no | 0-based frame index at the native fps (or give t) |
| `t` | number or null | no | Seconds into the clip (or give frame) |
| `bbox` | array or null | no | [x, y, w, h] normalised 0-1, top-left origin |
| `player_id` | integer or null | no | App player id (from detections) |
| `jersey_number` | integer or null | no | Shirt number 0-99 |
| `team` | string or null | no | CV team label A / B (optional) |

**Example**

```http
POST /api/videos/7/tracks
{
  "frame": 50,
  "bbox": [
    0.6595,
    0.7856,
    0.0307,
    0.1344
  ],
  "jersey_number": null,
  "team": "A"
}
```

Response **202**:

```json
{
  "track_id": 1,
  "video_id": 7,
  "status": "queued",
  "stage": "queued",
  "progress": 0,
  "error_message": null,
  "error_code": null,
  "target": {
    "mode": "bbox",
    "player_id": null,
    "jersey_number": null,
    "team": "A",
    "frame": 50,
    "t": 2.0,
    "bbox": [
      0.6595,
      0.7856,
      0.0307,
      0.1344
    ]
  },
  "fps": 25.0,
  "frame_count": 150,
  "width": 1280,
  "height": 720,
  "annotated_url": null,
  "frames_url": "/api/tracks/1/frames?token=<JWT>",
  "source": null,
  "summary": null,
  "stats": null,
  "warnings": [],
  "created_at": "2026-10-03T03:55:11Z",
  "updated_at": "2026-10-03T03:55:11Z",
  "finished_at": null
}
```

**Status codes:** `202`, `404`, `409`, `503`; errors: 401 missing/invalid/expired Bearer token; 404 video not found / not yours; 409 video not processed yet (same body as /stats), or a track is already queued/processing for this video: {detail, track_id, status, progress}; 422 none of bbox+frame/t, player_id, jersey_number; bbox without frame/t; both frame and t; bbox not normalised [x, y, w, h] inside 0-1 or < 2 px; frame/t outside the clip; jersey not 0-99; team not A/B; player_id unknown / not yours / not in this video; 503 migration 008 not run yet

### GET /api/videos/{video_id}/tracks

**Auth:** Bearer token

This video's tracks, newest first.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `video_id` | path | integer | yes |  |

**Example**

```http
GET /api/videos/7/tracks
```

Response **200**:

```json
[
  {
    "track_id": 1,
    "video_id": 7,
    "status": "done",
    "stage": "done",
    "progress": 100,
    "error_message": null,
    "error_code": null,
    "target": {
      "mode": "bbox",
      "player_id": null,
      "jersey_number": 7,
      "team": "A",
      "frame": 50,
      "t": 2.0,
      "bbox": [
        0.6595,
        0.7856,
        0.0307,
        0.1344
      ]
    },
    "fps": 25.0,
    "frame_count": 150,
    "width": 1280,
    "height": 720,
    "annotated_url": "/api/tracks/1/annotated.mp4?token=<JWT>",
    "frames_url": "/api/tracks/1/frames?token=<JWT>",
    "source": "stub",
    "summary": {
      "tracked_frames": 80,
      "occluded_frames": 24,
      "lost_frames": 46,
      "coverage_pct": 69.3,
      "avg_conf": 0.832,
      "reacquisition_count": 2,
      "lost_segments": [
        [
          17,
          40
        ],
        [
          98,
          119
        ]
      ],
      "player_uid": "stub-7-50",
      "track_ids": [
        1
      ],
      "schema_version": "stub-1",
      "pipeline_version": "stub-1",
      "tracker": "stub"
    },
    "stats": {
      "jersey_number": 7,
      "team": "A",
      "player_uid": "stub-7-50",
      "top_speed_mph": 20.67,
      "top_speed_kmh": 33.27,
      "distance_km": 0.007,
      "distance_m": 7.2,
      "minutes_played": 0.1,
      "minutes_played_s": 6.0,
      "visible_minutes": 0.07,
      "visible_minutes_s": 4.2,
      "distance_per_min_m": null,
      "coverage_pct": 69.3,
      "sprint_count": 0,
      "hsr_count": 0,
      "injury_risk": "Low"
    },
    "warnings": [
      "STUB: fake demo track generated by backend/tracking.py"
    ],
    "created_at": "2026-10-03T03:55:11Z",
    "updated_at": "2026-10-03T03:55:12Z",
    "finished_at": "2026-10-03T03:55:12Z"
  }
]
```

**Status codes:** `200`, `404`, `503`; errors: 401 missing/invalid/expired Bearer token; 404 video not found / not yours; 503 migration 008 not run yet; `422` invalid parameters

### GET /api/tracks/{track_id}

**Auth:** Bearer token

Status / stage / progress (poll every 1-2 s while queued|processing). When done: annotated_url, summary,
stats, source. frames_url / annotated_url carry fresh short-lived tokens on every fetch.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `track_id` | path | integer | yes |  |

**Example**

```http
GET /api/tracks/1
```

Response **200**:

```json
{
  "track_id": 1,
  "video_id": 7,
  "status": "done",
  "stage": "done",
  "progress": 100,
  "error_message": null,
  "error_code": null,
  "target": {
    "mode": "bbox",
    "player_id": null,
    "jersey_number": 7,
    "team": "A",
    "frame": 50,
    "t": 2.0,
    "bbox": [
      0.6595,
      0.7856,
      0.0307,
      0.1344
    ]
  },
  "fps": 25.0,
  "frame_count": 150,
  "width": 1280,
  "height": 720,
  "annotated_url": "/api/tracks/1/annotated.mp4?token=<JWT>",
  "frames_url": "/api/tracks/1/frames?token=<JWT>",
  "source": "stub",
  "summary": {
    "tracked_frames": 80,
    "occluded_frames": 24,
    "lost_frames": 46,
    "coverage_pct": 69.3,
    "avg_conf": 0.832,
    "reacquisition_count": 2,
    "lost_segments": [
      [
        17,
        40
      ],
      [
        98,
        119
      ]
    ],
    "player_uid": "stub-7-50",
    "track_ids": [
      1
    ],
    "schema_version": "stub-1",
    "pipeline_version": "stub-1",
    "tracker": "stub"
  },
  "stats": {
    "jersey_number": 7,
    "team": "A",
    "player_uid": "stub-7-50",
    "top_speed_mph": 20.67,
    "top_speed_kmh": 33.27,
    "distance_km": 0.007,
    "distance_m": 7.2,
    "minutes_played": 0.1,
    "minutes_played_s": 6.0,
    "visible_minutes": 0.07,
    "visible_minutes_s": 4.2,
    "distance_per_min_m": null,
    "coverage_pct": 69.3,
    "sprint_count": 0,
    "hsr_count": 0,
    "injury_risk": "Low"
  },
  "warnings": [
    "STUB: fake demo track generated by backend/tracking.py"
  ],
  "created_at": "2026-10-03T03:55:11Z",
  "updated_at": "2026-10-03T03:55:12Z",
  "finished_at": "2026-10-03T03:55:12Z"
}
```

**Status codes:** `200`, `404`, `503`; errors: 401 missing/invalid/expired Bearer token; 404 track not found / not yours; 503 migration 008 not run yet; `422` invalid parameters

### DELETE /api/tracks/{track_id}

**Auth:** Bearer token

Deletes the track and its files (track_<track_id>/). Allowed while running: the worker notices and stops.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `track_id` | path | integer | yes |  |

**Example**

```http
DELETE /api/tracks/1
```

Response **204** (no body)

**Status codes:** `204`, `404`; errors: 401 missing/invalid/expired Bearer token; 404 track not found / not yours; `422` invalid parameters

### GET /api/tracks/{track_id}/frames

**Auth:** Bearer token; or the short-lived `?token=` from `frames_url` (this track only)

Per-frame boxes of the tracked player: `{track_id, source, fps, width, height, frame_count, start, end,
frames:[{f, t, bbox [x,y,w,h] 0-1 | null, conf, state tracked|occluded|lost, pitch_x, pitch_y}]}`. Dense:
one entry per frame in [start, end]. `occluded` = interpolated estimate; `lost` = bbox null, conf 0.
Auth: Bearer, or the `?token=` in frames_url.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `track_id` | path | integer | yes |  |
| `start` | query | integer or null | no | First frame (inclusive, default 0) |
| `end` | query | integer or null | no | Last frame (inclusive, default last) |
| `token` | query | string or null | no | Media token from frames_url |

**Example**

```http
GET /api/tracks/1/frames?token=<JWT>&start=48&end=52
```

Response **200**:

```json
{
  "track_id": 1,
  "source": "stub",
  "fps": 25.0,
  "width": 1280,
  "height": 720,
  "frame_count": 150,
  "start": 48,
  "end": 52,
  "frames": [
    {
      "f": 48,
      "t": 1.92,
      "bbox": [
        0.653,
        0.7835,
        0.0307,
        0.1344
      ],
      "conf": 0.866,
      "state": "tracked",
      "pitch_x": null,
      "pitch_y": null
    },
    {
      "f": 49,
      "t": 1.96,
      "bbox": [
        0.6562,
        0.7844,
        0.0307,
        0.1344
      ],
      "conf": 0.892,
      "state": "tracked",
      "pitch_x": null,
      "pitch_y": null
    },
    "... 3 more"
  ]
}
```

**Status codes:** `200`, `401`, `404`, `409`; errors: 401 no Bearer token and no valid ?token= (expired, forged, other track); 404 track not found / not yours; 409 not done yet / failed: {detail, status, stage, progress, error_message, error_code}; 422 start > end

### GET /api/tracks/{track_id}/annotated.mp4

**Auth:** Bearer token; or the short-lived `?token=` from `annotated_url` (this track only). Also answers `HEAD`

Annotated video (H.264 yuv420p, faststart; same fps and frame count as the source). Auth: Bearer, or the
`?token=` in annotated_url (scoped to this track, short-lived; re-fetch the track for a fresh URL).
Full HTTP Range support for seeking.

| Parameter | In | Type | Required | Notes |
|---|---|---|---|---|
| `track_id` | path | integer | yes |  |
| `token` | query | string or null | no | Media token from annotated_url (for <video src>) |

**Example**

```http
GET /api/tracks/1/annotated.mp4?token=<JWT>
Range: bytes=0-1023
```

Response **206**:

```json
<video/mp4 1024 bytes>
```

**Status codes:** `200`, `206`, `401`, `404`, `409`, `416`; errors: 401 no Bearer token and no valid ?token= (expired, forged, other track); 404 track not found / not yours; 409 not done yet / failed (same body as /frames); 416 Range not satisfiable (Content-Range: bytes */<size>); `422` invalid parameters

