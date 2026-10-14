# Soccer Video Analytics – Backend (FastAPI + MySQL)

REST API for the End-to-End Computer Vision capstone. Serves per-player analytics
(top speed, distance, injury risk) to the React/Vite dashboard in `../frontend`,
handles user accounts (JWT), video uploads, and runs the CV pipeline (`../cv`, PR #1) in the background.

Repo-level docs: [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) (diagrams, ERD, data flow, config) and
[`../docs/API.md`](../docs/API.md) (every endpoint with examples). Run backend + frontend together with `../scripts/dev.sh`.

## Layout

| Path | Purpose |
|------|---------|
| `main.py` | FastAPI app, CORS, `/health`, `/api/players/stats` + `/api/players/{id}`, mounts routers |
| `routers/auth.py` | register / login / token / me (GET + PATCH) / change-password |
| `routers/videos.py` | upload, list, detail, per-video stats, thumbnail, delete |
| `routers/meta.py` | public `/api/config` |
| `routers/matches.py` | `/api/matches` list/detail, PATCH score/result/our_side, match tags |
| `routers/tags.py` | `/api/tags` catalog (keys, values, counts) |
| `routers/metrics.py` | `/api/metrics` registry, player metric history, video/player heatmaps |
| `routers/insights.py` | `/api/insights` (tag-grouped comparisons + next-match effect) |
| `routers/tracking.py` | Player tracking ("tracks" contract): `/api/videos/{id}/frame`, `/detections`, `/tracks`, `/api/tracks/{track_id}` (+ `/frames`, `/annotated.mp4` with HTTP Range) |
| `media.py` | Shared media helpers: Bearer-or-`?token=` auth for `<img>`/`<video>` URLs and single-range HTTP responses (used by `/source`, `/frame`, `/frames`, `/annotated.mp4`) |
| `metrics_catalog.py` | Metric registry (keys, units, aggregation), pipeline key aliases, heatmap grid |
| `match_logic.py` | Match ownership, "our side", W/D/L from scores |
| `tagging.py` | Tag normalization, add/replace/remove, `?tag=` filters |
| `thumbnails.py` | Optional JPEG thumbnail (ffmpeg, else cv2; never fails processing) |
| `pipeline.py` | Adapter that runs `cv/run_pipeline.py` (or a stub) and loads its output into MySQL |
| `tracking.py` | Player-tracking adapter: `cv.detect_frame` / `cv.track_player` command builders, background track worker, pixel → normalised `[x, y, w, h]` conversion and per-frame `state` normalisation, stub (fake track + ffmpeg annotated MP4) |
| `security.py` | bcrypt password hashing, JWT create/verify, `get_current_user` |
| `stats.py` | Shared per-player aggregation |
| `timeutil.py` | UTC helpers (`utcnow`, ISO-8601 `Z` serialization) |
| `config.py` | Settings from env / `.env` |
| `database.py`, `models.py`, `schemas.py` | SQLAlchemy engine, ORM models (mirror `schema.sql`), Pydantic models |
| `schema.sql` | MySQL 8 DDL for a **fresh** database |
| `migrations/000_legacy_erd_compat.sql` … `008_player_tracks.sql` | Upgrade an existing database in place (run in order; each is safe to re-run) |
| `seed.py` | Idempotent sample data (wipes all tables first): 7 matches with scores/tags, 5 videos, metrics, heatmaps |
| `uploads/` | Uploaded videos (`<uuid>.<ext>`), `thumbnails/<id>.jpg`, `cv_outputs/video_<id>/`, `cv_outputs/frames/video_<id>/` and `cv_outputs/track_<track_id>/` (gitignored) |
| `tests/` | pytest suite (temp SQLite + temp dirs; never touches MySQL, `.env` or `uploads/`) |

## Prerequisites (macOS, Apple Silicon)

- Python 3.11–3.13 (`python3 --version`)
- MySQL 8+ server. If you don't already have it:

  ```bash
  brew install mysql
  brew services start mysql
  ```

## Setup & run

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env:
#   DATABASE_URL=mysql+pymysql://root:YOUR_PASSWORD@localhost:3306/soccer_analytics_db
#   JWT_SECRET=<output of: python -c "import secrets; print(secrets.token_urlsafe(48))">
```

**Database: pick ONE of these.**

```bash
# A) Fresh database (nothing created yet)
mysql -u root -p < schema.sql

# B) Existing database: upgrade it in place, IN ORDER (all are safe to re-run, and a run that stopped
#    half-way can simply be started again). Back it up first:
#      mysqldump -u root -p --set-gtid-purged=OFF soccer_analytics_db > ~/soccer_analytics_db_backup.sql
#    The files say `USE soccer_analytics_db;`. For a different database name, strip that line:
#      sed '/^USE /d' migrations/004_player_metrics.sql | mysql -u root -p my_other_db
mysql -u root -p < migrations/000_legacy_erd_compat.sql   # original ERD (INT UNSIGNED keys, km/h + metres, x_center bboxes); no-op otherwise
mysql -u root -p < migrations/001_auth_videos.sql
mysql -u root -p < migrations/002_stats_per_video.sql
mysql -u root -p < migrations/003_video_progress_thumbnails.sql
mysql -u root -p < migrations/004_player_metrics.sql      # metric registry, per-player metrics, heatmaps
mysql -u root -p < migrations/005_tags_results.sql       # match scores/result/our_side, tags (backfills weather)
mysql -u root -p < migrations/006_pipeline_v120.sql      # CV v1.2.0: heatmap source/unit, new metric definitions
mysql -u root -p < migrations/007_video_player_overrides.sql  # v0.4.1: per-video jersey corrections table, metric definitions refresh
mysql -u root -p < migrations/008_player_tracks.sql           # v0.5.0: player_tracks table
mysql -u root -p < migrations/009_erd_parity.sql              # v0.6.0: ERD columns on soccer_analytics_app
#    Foreign-key columns added by 001-008 take the type of the key they reference (INT or INT UNSIGNED).
#    Tested on MySQL 26.7: the original ERD (including the half-applied 001-003 state), a step-2 database, and a
#    fresh schema.sql (where every migration is a no-op). MySQL 8.0.20+ prints deprecation warnings (code 1287)
#    for VALUES() in 004/006/007; they're harmless. The row-alias form isn't used because MariaDB doesn't support it.
```

Then:

```bash
python seed.py                     # OPTIONAL: wipes ALL rows (incl. registered users) & loads sample data
uvicorn main:app --reload          # http://localhost:8000   (interactive docs: /docs)
```

Seed demo login: `faisal@example.com` / `capstone123`.
If root has no password, drop `-p`. URL-encode special characters (`@ : / #`) in the password inside `DATABASE_URL`.

## API

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/health` | – | `{"status":"ok","db":"ok"\|"unreachable"}`, never 500s |
| GET | `/api/players/stats` | – | Bare array `{player_id,name,top_speed_mph,distance_km,injury_risk}` aggregated over **all** stats rows (every video + legacy rows, all users: public and unscoped, as before); `?match_id=` `?team_id=`; `?include=metrics[&metrics=k1,k2]` adds `metrics` + `avg_position` (see Metrics). `top_speed_mph`/`distance_km` can be `null` (see below) |
| GET | `/api/players/{player_id}` | – | 404 if missing |
| GET | `/api/config` | – | `{"max_upload_mb":500,"allowed_extensions":["avi","mkv","mov","mp4"]}` |
| POST | `/api/auth/register` | – | JSON `{email,password}` + either `name` ("First Last", split on the first space) or `first_name` (+ optional `last_name`) → 201: the user object **plus** `access_token`, `token_type`, `expires_in` and a nested `user` (so you're logged in straight away); 409 duplicate email; password 8–72 bytes |
| POST | `/api/auth/login` | – | JSON `{email,password}` **or** a form (`username`=email, `password`; urlencoded or multipart) → `{access_token,token_type:"bearer",expires_in,user}`; 401 bad credentials; 422 malformed body |
| POST | `/api/auth/token` | – | OAuth2 form only (`username`=email, `password`), same response. Used by the **Authorize** button in `/docs` |
| GET | `/api/auth/me` | Bearer | User object (below) |
| PATCH | `/api/auth/me` | Bearer | `{name}` and/or `{first_name,last_name}` (explicit fields win over `name`) → 200 user; 422 empty body / blank name |
| POST | `/api/auth/change-password` | Bearer | `{current_password,new_password}` → 204; **400** wrong current password (not 401, so the UI doesn't log you out) or new == current; 422 new password not 8–72 bytes |
| POST | `/api/videos` | Bearer | multipart: `file` (see `/api/config`), `title`, and either `match_id` (numeric string, e.g. `"12"`; `""`/`"null"`/`"undefined"` = not given; anything else → 422; not yours → 404) **or** `match_date` (YYYY-MM-DD) + `home_team` + `away_team` (teams/match are found or created for you). → 202 video detail object, status `queued` |
| GET | `/api/videos` | Bearer | **Bare array** of video objects (no `pipeline_meta`), newest first |
| GET | `/api/videos/{id}` | Bearer | Video object + `pipeline_meta`. 404 if not yours |
| GET | `/api/videos/{id}/stats` | Bearer | Same shape as `/api/players/stats` (incl. `?include=metrics`), for **this video** only. **409** `{"detail":"Video not processed yet"\|"Video processing failed","status","stage","progress","error_message"}` unless status is `done` (`error_message` is set for failed videos, else null); done with no rows → `[]` |
| GET | `/api/videos/{id}/thumbnail` | Bearer **or** `?token=` | `image/jpeg`; 404 if not yours / no thumbnail. See "Thumbnails" |
| DELETE | `/api/videos/{id}` | Bearer | Owner only → 204. Removes the row (stats + detections cascade), the upload, thumbnail, `cv_outputs/video_<id>/` and that video's `Unknown Track N (video <id>)` placeholder players. If it was the match's last video and nothing else references the match (no legacy stats), your tags on that match are removed too (the match itself is kept). Allowed while processing (the pipeline subprocess is killed). 404 if not yours |
| PATCH | `/api/videos/{id}/players/{player_id}` | Bearer | `{jersey_number: 0-99 or null}` (required; null = no number) → 200, the player's row in the `/stats` shape. Per-video override (`video_player_overrides`); the roster and other videos are unchanged. 404 not your video / player not in it, 409 not processed yet or a teammate already has that number in this video, 422 invalid, 503 migration 007 not run |
| GET | `/api/videos/{id}/source` | Bearer **or** `?token=` | The original upload (`source_url` on every video object carries the token; null if the file is gone). HTTP Range (206 / 416, `Accept-Ranges`, `ETag`, `If-Range`) and `HEAD`, for the live canvas overlay |
| GET | `/api/videos/{id}/frame` | Bearer **or** `?token=` | `image/jpeg` of `?frame=<n>` (default 0) or `?t=<sec>` (`frame_url` from `/detections` carries the token) |
| GET | `/api/videos/{id}/detections` | Bearer | `?frame=<n>` (default 0) or `?t=<sec>` → `{frame, t, width, height, frame_url, source, players:[{player_id, jersey_number, team:"A"/"B"/null, class, bbox:[x,y,w,h] 0-1, conf}]}`; cached per (video, frame). 422 outside the clip, 503 CV tracking forced real but missing, 502/504 `cv.detect_frame` failed / timed out. See "Player tracking" |
| POST | `/api/videos/{id}/tracks` | Bearer | `{frame?\|t?, bbox?, player_id?, jersey_number?, team?}`: needs bbox + frame/t, **or** player_id, **or** jersey_number (team always optional) → **202 with the full track object** (background). 409 video not done / a track is already active (`{detail, track_id, status, progress}`), 422 bad target, 503 migration 008 not run |
| GET | `/api/videos/{id}/tracks` | Bearer | This video's tracks, newest first |
| GET | `/api/tracks/{track_id}` | Bearer | Track: `status` queued/processing/done/failed, `stage` (queued/detect/tracking/rendering/done/failed), `progress`, `error_message`, `error_code`, `target {mode, player_id, jersey_number, team, frame, t, bbox}`, `fps`, `frame_count`, `width`, `height`, `frames_url`, and when done `annotated_url`, `source`, `summary`, `stats` |
| GET | `/api/tracks/{track_id}/frames` | Bearer **or** `?token=` | `?start=&end=` (inclusive) → `{track_id, source, fps, width, height, frame_count, start, end, frames:[{f, t, bbox:[x,y,w,h]\|null, conf, state tracked/occluded/lost, pitch_x, pitch_y}]}` (dense); 409 until done |
| GET | `/api/tracks/{track_id}/annotated.mp4` | Bearer **or** `?token=` | Annotated H.264 MP4 (same fps + frame count as the source) with HTTP Range (206 / 416) and `HEAD`; use `annotated_url` as `<video src>` |
| DELETE | `/api/tracks/{track_id}` | Bearer | 204; removes the track and `cv_outputs/track_<track_id>/` (allowed while running) |
| GET | `/api/matches` | Bearer | Matches involving your teams, newest first: bare array of match objects (see "Results"). `?tag=key:value` repeatable |
| GET | `/api/matches/{id}` | Bearer | Match object; 404 if not yours |
| PATCH | `/api/matches/{id}` | Bearer | Any of `{home_score, away_score, our_side, result}` → 200 match object. See "Results" |
| GET / POST / PUT / DELETE | `/api/matches/{id}/tags` | Bearer | See "Tags" |
| GET / POST / PUT / DELETE | `/api/videos/{id}/tags` | Bearer | Same, acting on the video's match |
| GET | `/api/tags` | Bearer | `[{key, values:[{value,count}]}]` (count = your matches with that tag), keys/values sorted |
| GET | `/api/tags/keys` | Bearer | `[{key, value_count, match_count}]` (key autocomplete) |
| GET | `/api/tags/values?key=&q=` | Bearer | `[{key, value, count}]` (value autocomplete; `q` = case-insensitive prefix) |
| GET | `/api/metrics` | – | Metric registry (see "Metrics") |
| GET | `/api/players/{id}/metrics?metrics=` | Bearer | Per-match history of one of **your** players (404 otherwise) |
| GET | `/api/videos/{id}/heatmap?player_id=` | Bearer | Per-player position heatmaps for a processed video (409 like `/stats`) |
| GET | `/api/players/{id}/heatmap?video_id=&match_id=` | Bearer | Summed heatmap of one of your players |
| GET | `/api/insights?tag_key=&player_id=&team_id=` | Bearer | Tag-grouped comparison + next-match effect. Alias: `/api/insights/tags?key=` |

Error codes: 400 bad request (e.g. wrong current password), 401 missing/invalid token, 404 not yours / no such route,
405 wrong method, 409 duplicate email / stats not ready, 413 too large, 415 wrong type / content isn't a video,
422 validation, 500 unexpected error, 503 database down.

**Every error body is JSON with a `detail` key**: `{"detail": "<message>"}`; FastAPI's own request-validation 422s
use `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}` (also used for a bad upload `match_id`). The stats 409 adds
`status`, `stage`, `progress`, `error_message` next to `detail`. Unhandled errors return 500
`{"detail":"Internal server error"}` with CORS headers (details only in the server log).

**Timestamps**: all `DATETIME` columns store **UTC** (naive). The app writes `utcnow()` and sets every MySQL session to
`time_zone = '+00:00'`, so `CURRENT_TIMESTAMP` defaults are UTC too. Responses serialize `created_at`, `uploaded_at`,
`processed_at` (videos and users) as ISO 8601 with `Z`, e.g. `"2026-09-30T22:27:43Z"`; `new Date(value)` parses them
correctly. `match_date` stays a plain `YYYY-MM-DD` date. Exception: `pipeline_meta.start_timestamp`/`end_timestamp`
are copied raw from the pipeline's `meta.json` (the CV machine's local time, no offset).
Rows written **before** this change hold your Mac's local time (EDT). If they matter, either re-seed (`python seed.py`,
wipes everything) or shift them **once** (not re-runnable!):
`UPDATE users SET created_at = created_at + INTERVAL 4 HOUR; UPDATE match_videos SET uploaded_at = uploaded_at + INTERVAL 4 HOUR, processed_at = processed_at + INTERVAL 4 HOUR;`

**User object** (`/me`, PATCH `/me`, login `user`, register):
`{"id":1,"user_id":1,"name":"Faisal Musa","first_name":"Faisal","last_name":"Musa","email":"...","role":"analyst","created_at":"2026-09-30T22:27:42Z"}` (`id` = `user_id`)

**Video object** (list items; detail adds `"pipeline_meta": {...}` = the pipeline's `meta.json` + `adapter_*` info):

```json
{"id":3,"video_id":3,"match_id":4,"title":"Derby first half","file_name":"clip.mp4",
 "match_date":"2026-09-29","home_team":"Capstone FC","away_team":"Rival United",
 "status":"processing","stage":"detect","progress":46,"error_message":null,"error":null,
 "created_at":"2026-09-30T21:20:19Z","uploaded_at":"2026-09-30T21:20:19Z","processed_at":null,
 "fps":null,"duration_seconds":null,"thumbnail_url":"/api/videos/3/thumbnail?token=<jwt>",
 "source_url":"/api/videos/3/source?token=<jwt>",
 "match":{"match_id":4,"match_date":"2026-09-29","home_team":"Capstone FC","away_team":"Rival United",
          "home_score":2,"away_score":1,"result":"W"},
 "tags":[{"key":"pitch","value":"Grass"},{"key":"weather","value":"Rainy"}]}
```

- `video_id` is an alias of `id` (kept for backward compatibility). `created_at` = `uploaded_at`. `error` = `error_message`.
- `status`: `queued` → `processing` → `done` | `failed`.
- `stage` / `progress` (0–100 int, never goes backwards): `queued` 0 → `detect` 10 (then 10–70 from the
  pipeline's `Processing frames: N%` log line) → `track` 72 → `ocr` 75 → `metrics` 78–80 → `ingest` 90 → `done` 100.
  On failure `stage` = `failed` and `progress` stays where it stopped. Poll `/api/videos/{id}` every ~2 s.
- `tags` = the tags of the video's **match** (list and detail). `result` = the match's W/D/L (our side), or null.
- Upload also accepts optional form fields `tags` (JSON string: `[{"key":"weather","value":"Rainy"}]` or `{"tags":[...]}`; added to the match; bad JSON → 422) and `our_side` (`home`|`away`, else 422).
- `duration_seconds` = `meta.json` `duration_s` (null until the pipeline finished / if absent). `fps` likewise.

**Thumbnails**: generated right after processing starts from ~1 s into the video (ffmpeg if on PATH, else OpenCV if
importable in the backend venv; otherwise `thumbnail_url` is `null` — processing never fails because of it).
Uploads are private, so there is no StaticFiles mount. Because `<img>` can't send an `Authorization` header,
`thumbnail_url` embeds a short-lived **thumbnail-only** token (`type=thumb`, bound to that one video, expires after
`THUMBNAIL_TOKEN_EXPIRE_MINUTES`, default 60; a fresh URL is issued on each list/detail call). Use it as
`<img src={API_URL + video.thumbnail_url}>`. Normal access tokens are rejected in `?token=` (they never go in URLs),
and thumbnail tokens are rejected everywhere else. `fetch` with a Bearer header also works.

`source_url` (v0.5.0) works the same way for the original upload: `GET /api/videos/{id}/source?token=...` (media
token scoped to `source:<video_id>`, `MEDIA_TOKEN_EXPIRE_MINUTES`), with HTTP Range so `<video src>` can seek. It is
`null` when the uploaded file is no longer on disk.

`/api/players/stats` is declared **before** `/api/players/{player_id}` on purpose. Keep new static
`/api/players/...` routes above the `{player_id}` route.

## curl walkthrough

```bash
B=http://localhost:8000
curl $B/health

curl -X POST $B/api/auth/register -H 'Content-Type: application/json' \
  -d '{"name":"Faisal Musa","email":"me@example.com","password":"s3cure-pass!"}'

TOKEN=$(curl -s -X POST $B/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"s3cure-pass!"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl $B/api/auth/me -H "Authorization: Bearer $TOKEN"
curl -X PATCH $B/api/auth/me -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name":"Faisal A. Musa"}'
curl $B/api/config

curl -X POST $B/api/videos -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/clip.mp4" -F "title=Derby first half" \
  -F "match_date=2026-09-27" -F "home_team=Capstone FC" -F "away_team=Rival United"
# -> {"id":1,"video_id":1,...,"status":"queued","stage":"queued","progress":0,...}

curl $B/api/videos -H "Authorization: Bearer $TOKEN"
curl $B/api/videos/1 -H "Authorization: Bearer $TOKEN"        # poll until "done" or "failed"
curl $B/api/videos/1/stats -H "Authorization: Bearer $TOKEN"     # 409 until done
curl $B/api/matches -H "Authorization: Bearer $TOKEN"
curl -X DELETE $B/api/videos/1 -H "Authorization: Bearer $TOKEN"  # 204
curl $B/api/players/stats
```

## CV pipeline integration

After an upload, a FastAPI BackgroundTask (`pipeline.process_video`) sets the video to `processing`,
runs the pipeline, loads its output, then sets `done` (with `processed_at`) or `failed` (with `error_message`).

The real pipeline is `cv/run_pipeline.py` from PR #1 (branch `cursor/soccer-cv-pipeline-236d`, not merged yet).
The backend runs it as a module from the repo root, as agreed with the CV engineer:

```
cd <repo root> && PYTHONPATH=<repo root> $CV_PYTHON -m cv.run_pipeline \
    --video uploads/<uuid>.mp4 --out uploads/cv_outputs/video_<id> \
    --device $CV_DEVICE [--calibration $CV_CALIBRATION_PATH] [--model $CV_MODEL] $CV_EXTRA_ARGS
```

(`<repo root>` is derived from `CV_PIPELINE_PATH`; YOLO weights auto-download into the repo root, `*.pt` is gitignored.)
It then reads `tracking_detections.json`, `player_match_stats.json` and, if present, `meta.json` and `heatmaps.json` from the output
folder. The full log is at `uploads/cv_outputs/video_<id>/pipeline.log`.

What the adapter does with the output:

- **Stats are stored per video**: `player_match_stats.video_id` (unique per player+video). Re-processing a video
  replaces only that video's rows. `/api/players/stats` still sums/maxes across all rows.
- **No calibration → `top_speed_mph`/`distance_km` are `null`**: stored as NULL and returned as `null`
  (the keys are always present). Aggregation ignores NULLs (SQL MAX/SUM); a player whose values are all NULL gets `null`.
  The frontend should render `null` as "–".
- **`meta.json`** (fps, frame_count, duration, resolution, model, device, calibration, pipeline_version, runtime,
  warnings) is stored as JSON in `match_videos.pipeline_meta` and returned by `/api/videos/{id}`; `fps` is taken
  from it (fallback: estimated from frame/timestamp).
- **Extended metrics** (v1.1.1: `high_speed_distance_km`, `sprint_distance_km`, `sprint_count`; v1.2.0: minutes,
  coverage, zones, counts, accel/decel estimates, positions) go to `player_match_metrics`; `heatmaps.json` (v1.2.0) or,
  as a fallback, detections with pitch coordinates feed the heatmaps (see Metrics).
- **`team` / `role`** (pipeline v1.1.0+): `team` 0 = home, 1 = away, null = unassigned
  (mapping lives in `pipeline.team_side()`); rows with `role == "referee"` are skipped for stats and never linked
  to a player (detections are still stored with `object_class = "referee"`). Missing fields are tolerated.

Settings (`.env`):

| Var | Default | Meaning |
|-----|---------|---------|
| `THUMBNAILS_ENABLED` | `true` | Generate thumbnails (ffmpeg/cv2) |
| `THUMBNAIL_TOKEN_EXPIRE_MINUTES` | `60` | Lifetime of the `?token=` in `thumbnail_url` |
| `CV_PIPELINE_MODE` | `auto` | `auto`: real if `CV_PIPELINE_PATH` exists, else stub if `CV_PIPELINE_STUB=true`, else fail the video. `real` / `stub` force one |
| `CV_PIPELINE_STUB` | `false` (`.env.example`: `true`) | Allow the **STUB**: FAKE demo stats (logged as a warning, and `STUB_OUTPUT_FAKE_DATA.txt` is written in the output dir) |
| `CV_PIPELINE_PATH` | `../cv/run_pipeline.py` | Locates the CV checkout: path to `cv/run_pipeline.py`, the `cv/` dir, or the repo root |
| `CV_PYTHON` | backend's python | Interpreter of the CV venv (heavy deps: torch, ultralytics, easyocr). Python 3.11–3.13 supported |
| `CV_DEVICE` | `auto` | `mps` on Apple Silicon |
| `CV_CALIBRATION_PATH` | none | Optional. Without it, pipeline v1.1.x falls back to its generic `cv/config/default_calibration.json` (speed/distance approximate; a warning is in `pipeline_meta.warnings`, added once by v1.1.1 or by the adapter for older versions). `null` speed/distance only if no calibration is available at all |
| `CV_MODEL`, `CV_EXTRA_ARGS`, `CV_TIMEOUT_SECONDS` | | passed through / subprocess timeout |
| `TRACK_PIPELINE_MODE` | `auto` | Player tracking, **independent of `CV_PIPELINE_MODE`**. `auto`: real only if `cv/track_player.py` **and** `cv/detect_frame.py` exist under the CV repo root (from `CV_PIPELINE_PATH`), else the stub, so it switches to real by itself once the CV tracking PR is merged. `real`: always the CV modules (tracks fail with `error_code: cv_unavailable`, `/detections` 503, if missing). `stub`: always fake demo data. The mode is logged at startup (`Player tracking mode: ...`) and every finished track / detections response says `source: real|stub` |
| `CV_TRACK_TIMEOUT_SECONDS`, `CV_DETECT_TIMEOUT_SECONDS` | `7200`, `180` | Subprocess timeouts for `cv.track_player` / `cv.detect_frame` |
| `MEDIA_TOKEN_EXPIRE_MINUTES` | `60` | Lifetime of the `?token=` in `source_url` / `frame_url` / `frames_url` / `annotated_url` |
| `CV_CREATE_UNKNOWN_PLAYERS` | `true` | Tracks whose OCR jersey number doesn't match a rostered player get a placeholder player (`Unknown #7` / `Unknown Track 12`) on the home team |

How tracks map to players: the jersey number (OCR majority vote) is matched against the roster of the track's
`team` when the pipeline provides it, otherwise home roster first, then away. Unmatched tracks get placeholders:
`Unknown #7` (reused across videos for that team) or `Unknown Track 12 (video 5)` (per video, since track ids
restart every video). Multiple tracks for the same player in one video are merged (max speed, summed distance,
worst risk). All detections go into `tracking_detections` (`object_class` = player/goalkeeper/referee/ball,
`jersey_number`, `player_id` if mapped).

Example setup once PR #1 is merged (so `cv/` sits next to `backend/`):

```bash
cd ..            # repo root
python3 -m venv cv/venv && cv/venv/bin/pip install -r cv/requirements.txt   # Python 3.11–3.13
# backend/.env
CV_PIPELINE_MODE=auto
CV_PYTHON=/Users/faisalmusa/End-To-EndCompVisionCapstoneProject/cv/venv/bin/python
CV_DEVICE=mps
CV_CALIBRATION_PATH=/Users/faisalmusa/End-To-EndCompVisionCapstoneProject/cv/config/example_calibration.json
```

Notes: processing runs inside the API process, one thread per video. If the server restarts (including a
`--reload` after a code edit), videos still `queued`/`processing` are marked `failed` on startup; re-upload them.

## Metrics, heatmaps, tags, results, insights

### Metrics registry
`GET /api/metrics` returns the registry (table `metric_definitions`; source of truth `metrics_catalog.py`, re-synced at
startup and seeded by migrations 004/006): `[{key, label, unit, category, value_type, aggregation, decimals,
higher_is_better, requires_calibration, is_estimate, availability, storage, description, sort_order}]`. All 21 metrics
are `ready` with CV pipeline v1.2.0 (older pipelines leave the newer ones `null`).

| key | unit | aggregation | pipeline v1.2.0 source (older pipelines) |
|-----|------|-------------|------------------------------------------|
| `distance_km`, `top_speed_mph` | km, mph | sum, max | same keys (`player_match_stats` columns) |
| `top_speed_kmh` | km/h | max | `top_speed_kmh` (else mph × 1.60934) |
| `minutes_played` | min (2 dp) | sum | `minutes_played_s` / 60 (PR #2) else `minutes_played`, first to last seen (else video length `duration_s` / 60) |
| `visible_minutes` | min (2 dp) | sum | `visible_minutes_s` / 60 (PR #2) else `visible_minutes`, time actually tracked |
| `coverage_pct` | % | mean | `coverage_pct` (fragments of one player added, capped at 100) |
| `distance_per_min` | m/min | ratio: Σdistance·1000 / Σvisible_minutes (else Σminutes_played); **null under 0.1 min** | `distance_per_min_m` (same definition; recomputed from `distance_m` (PR #2) or `distance_km` after merging fragments; nulled under 0.1 min) |
| `avg_pitch_x`, `avg_pitch_y` → `avg_position` | m | mean | `avg_pitch_x/y`, weighted by visible minutes (else mean of mapped detections) |
| `hsr_distance_km` | km | sum | `high_speed_distance_km` |
| `sprint_distance_km` | km | sum | same key |
| `hsr_count`, `sprint_count` | count | sum | same keys |
| `high_intensity_efforts` | count | sum | `hi_efforts_count` (else `hsr_count + sprint_count`) |
| `accels`, `decels` (estimates) | count | sum | `accel_count_high`, `decel_count_high` |
| `zone1..zone5_distance_km` → `speed_zones.{walk,jog,run,hsr,sprint}` | km | sum | `zone_walk_km` … `zone_sprint_km` |

Per-player values live in `player_match_metrics` (`stat_id, metric_key, value`), so new metrics need **no schema
change**: add a row to `metrics_catalog.DEFINITIONS` (plus an alias in `PIPELINE_ALIASES` if the pipeline's name
differs). Unknown **numeric** keys in `player_match_stats.json` are ignored and listed in `pipeline_meta.warnings`;
unknown non-numeric keys (e.g. a future `player_uid`) are ignored silently. Counts are returned as ints. Fragmented
tracks of one player (same jersey) are merged: sums for distances/counts/minutes, max for speeds.
Without calibration v1.2.0 sends every physical field as `null`; those stay `null` (only `minutes_played` falls back to
the video length).

**Thresholds** (v1.1.2+/v1.2.0 `meta.json`: `speed_preset`, `hsr_threshold_kmh`, `sprint_threshold_kmh`,
`zone_edges_kmh {walk, jog, run, hsr}`) are kept in `pipeline_meta` and returned on every `/api/videos/{id}/stats` row as
`speed_thresholds: {preset, hsr_kmh, sprint_kmh, zone_edges_kmh, source}`. Missing keys (seeded rows from before
v0.4.1, older pipelines) are filled with the CV defaults `metrics_catalog.DEFAULT_SPEED_THRESHOLDS` (gps_standard: HSR
19.8, sprint 25.3 km/h, zone edges 7 / 15 / 19.8 / 25.3), values rounded to 0.1 km/h; `source` is `pipeline`, `default` or
`mixed`. No backfill needed. The seed and the stub write the same keys into `meta.json`.

**Rates on short clips:** `distance_per_min` is null when the player's minutes are under
`metrics_catalog.MIN_RATE_MINUTES` (0.1). This is applied at ingest and again when reading, so rows stored by v0.4.0
(e.g. the stub's 438,000 m/min on a 1 s clip) come back null without a backfill. The stub now derives the clip length
from the file (ffprobe, else OpenCV; 1 s if unreadable), minutes from the frames each player is visible, and distance
from 85–125 m/min.
`pipeline_meta.adapter_metrics` records which source was used: `{sources: {minutes_played: {pipeline|video_length: n},
avg_position: {pipeline|detections: n}, heatmap: {pipeline|backend: n}}, heatmap_grid: pipeline|backend|mixed|null,
speed_thresholds}`.

**Flat extras** (frontend contract): every `/api/videos/{id}/stats` row (and `/api/players/stats` rows with
`?include=metrics`) also has `jersey_number`, `top_speed_kmh`, `minutes_played`, `visible_minutes`, `coverage_pct`,
`distance_per_min`, `hsr_distance_km`, `sprint_distance_km`, `hsr_count`, `sprint_count`, `high_intensity_efforts`,
`accels`, `decels` (null if unknown), `speed_zones` (`{walk, jog, run, hsr, sprint}` km, or null), `avg_position`
(`{x, y}` m), `heatmap` (`{cols, rows, cells:[cols×rows values 0–1, row-major], samples, source, cell_unit,
pitch_length_m, pitch_width_m}` or null) and (video stats) `speed_thresholds`. The five base fields are unchanged.
`/api/players/stats` without `include` keeps the exact 5-field shape.

`?include=metrics` on `/api/players/stats` and `/api/videos/{id}/stats` adds to each row
`"metrics": {"distance_per_min": 78.0, "hsr_distance_km": 0.3, "sprint_count": 17, "accels": 6, ...}` (all keys, or
only `?metrics=k1,k2`).

`GET /api/players/{id}/metrics` → `{player_id, name, team_id, series:[{video_id, video_title, match_id, match_date,
home_team, away_team, result, top_speed_mph, distance_km, injury_risk, metrics, avg_position}], totals:{appearances,
top_speed_mph, distance_km, injury_risk, metrics, avg_position}}`, oldest first (legacy rows have `video_id: null`).

**Heatmaps**: `counts[row][col]`, `col` along the length (`pitch_x`), `row` along the width (`pitch_y`), row 0/col 0 =
pitch origin; `intensity` = counts / max (0–1). Which grid is used, per player per video:
1. **`source: "pipeline"`**: the CV pipeline's `heatmaps.json` (v1.2.0+, only with calibration): 21 × 14 cells of 5 ×
   ~4.9 m, `cell_unit: "seconds"` (time in cell); fragments of one player are added.
2. **`source: "backend"`** (fallback: older pipeline, missing/invalid grid): 12 × 8 grid computed from
   `tracking_detections`, `cell_unit: "samples"` (detections); points > 5 m off the pitch dropped.

`GET /api/videos/{id}/heatmap` → `{video_id, grid:{cols, rows, x_axis, y_axis, layout, source, cell_unit,
pitch_length_m, pitch_width_m}, players:[{player_id, name, samples, avg_position, cols, rows, source, cell_unit, counts,
intensity}]}` (top-level `grid` = the most common grid in that video; each player carries its own).
`GET /api/players/{id}/heatmap` → the grid info plus summed `counts`, `intensity`, `samples`, `videos`,
`videos_skipped`, `avg_position`. Grids of different shapes/units can't be added, so the group with the most samples is
used (tie: the pipeline grid) and the rest are counted in `videos_skipped`.

### Results and "our side"
Matches have `home_score`, `away_score`, `our_side` (`home`|`away`) and `result` (`W`|`D`|`L`). Match object:
`{match_id, match_date, home_team, away_team, home_team_id, away_team_id, video_count, home_score, away_score,
our_side, our_team, opponent, result, tags}`.
- **Our side** = the side whose team you own. If you own both teams (e.g. both created by the upload form), `our_side`
  decides (default `home`). Set it with the upload field or PATCH.
- **Result** is derived from the scores, from our side's view, whenever both scores are set. Without scores a manual
  `result` is kept (e.g. only W/D/L is known).
- PATCH rules: scores are set/cleared **in pairs** (else 422); a `result` that contradicts the scores → 422; clearing
  both scores clears the result; negative scores / empty body → 422; not yours → 404.

### Tags
Tags are **key/value pairs on the match** (`tag_keys` per user → `tag_values` → `match_tags`). Tagging a video tags its
match, so every video of one match shows the same tags, and insights count each match once.
- Keys (1–50 chars, no `:`, e.g. `Weather`, `Home/Away`) and values (1–100 chars) are trimmed, stored with the
  **first-seen casing** and matched **case-insensitively** everywhere ("weather"/"rainy" reuse "Weather"/"Rainy", so
  data doesn't split). Send display case.
- `GET …/tags` → `[{key, value}]`. `POST …/tags` `{tags:[{key,value}]}` (or a bare list) **adds**; `PUT` **replaces
  the full set** (`{tags:[]}` clears). On `/api/videos/{id}/tags` both return the **video object** (incl. `tags`); on
  `/api/matches/{id}/tags` they return the tag list. `DELETE …/tags?key=&value=` removes one value, or the
  whole key without `value` → 204 (idempotent). Invalid key/value → 422; not your video/match → 404.
- The backend allows several values per key (and up to 50 tags per request); the UI enforces one value per key and
  its own 12-tag / 40-char limits by sending the full set with PUT.
- Filters: `GET /api/videos?tag=Weather:Rainy&tag=Pitch:Turf`, same for `/api/matches`. **Same key = OR, different
  keys = AND**; keys and values case-insensitive; malformed (no `:`) → 422.
- Migration 005 backfills a `Weather` tag from the old `matches.weather_condition` column.
- Deleting a video: tags stay while the match has other videos (or legacy stats without a video); when the last one
  goes, your tags on that match are removed. Keys/values stay in your vocabulary (`/api/tags`), the match row stays.

### Insights
`GET /api/insights?tag_key=Weather[&player_id=|&team_id=]` (alias `/api/insights/tags?key=`; key case-insensitive; missing key → 422;
`player_id`/`team_id` not yours → 404). Scope: default = the players of **our team** in each match
(`scope: "our_team"`), or one team / one player.

```json
{"key":"weather","scope":"our_team","filters":{},"definitions":{},
 "baseline":{"matches":7,"matches_with_data":6,"metrics":{},"metric_n":{},"injury_risk":{"Low":9,"Medium":3,"High":0},
             "avg_distance_km":3.5,"avg_top_speed_mph":19.4,"avg_sprints":10.1,"avg_hsr_distance_km":0.4,
             "avg_workload":1.65,"workload":{"low":12,"medium":9,"high":3},
             "wdl":{"w":4,"d":1,"l":1,"unknown":1},"match_ids":[3,4,5,1,6,2,7]},
 "groups":[{"value":"Rainy","matches":3,"matches_with_data":3,"low_sample":false,
            "avg_distance_km":3.0,"avg_top_speed_mph":19.4,"avg_sprints":10.9,"avg_hsr_distance_km":0.4,
            "avg_distance_per_min":50.0,"avg_workload":1.9,"metrics":{},"metric_n":{},
            "delta_vs_baseline":{},"change_pct_vs_baseline":{},"injury_risk":{"Low":4,"Medium":4,"High":3},
            "workload":{"low":4,"medium":4,"high":3},
            "wdl":{"w":2,"d":0,"l":1,"unknown":0},"match_ids":[3,5,2],
            "next_match":{"match_ids":[4,1,7],"matches_with_data":2,"low_sample":true,"metrics":{},
                          "pairs":2,"wdl":{"w":1,"d":1,"l":0,"unknown":1},"delta":{},"change_pct":{}}}],
 "next_match_effect":[{"value":"Rainy","metric":"distance","metric_key":"distance_km","change_pct":10.7,
                       "delta":0.375,"next":3.877,"next_avg":3.877,"baseline":3.502,"n":2,"pairs":2,
                       "low_sample":true}]}
```
(Illustrative numbers; `{}` = abbreviated; `metrics`/`metric_n`/`delta*` are keyed by metric key.)

Definitions:
- Per match, each player's rows (all videos of that match) are combined with the registry aggregation, then averaged
  over the players in scope → one value per match. A group value = mean of its matches' values (each match counts
  once). `metric_n` = matches that had a value. `low_sample` = fewer than 3 matches with data (show, but don't rank).
- **`avg_workload`** = mean injury-risk band per player-match (Low = 1, Medium = 2, High = 3; range 1–3, lower =
  lighter). It is the pipeline's speed/distance-based workload flag, **not a medical assessment**; `injury_risk` has
  the band counts for a distribution bar.
- `avg_sprints` = mean `sprint_count` per player per match; `avg_distance_km` likewise.
- `wdl` counts every tagged match (`unknown` = no result yet).
- **Next match** = your chronologically next match (by date, then id) after each tagged match. `next_match_effect`
  compares the mean over those next matches with the baseline (all your matches) for `distance_km`, `top_speed_mph`,
  `sprint_count`, `hsr_distance_km`, `workload` (`metric` = `distance`|`speed`|`sprints`|`hsr`|`workload`,
  `metric_key` = registry key; `next` = `next_avg`). `n` = distinct next matches with data for that metric, `pairs` =
  tagged matches whose next match has data (both sides). Correlation, not cause.
- `workload` = `{low, medium, high}` band counts (same as `injury_risk`, lower-case keys).

Out of scope for now (the pipeline can't measure them): goal/assist/shot/xG events, passes, team compactness.

## Frontend

The dashboard reads `VITE_API_URL` (default `http://localhost:8000`). CORS allows `http://localhost:5173`
and `http://127.0.0.1:5173` (credentials + `Authorization` header). Change `CORS_ORIGINS` in `.env` if needed.
Send `Authorization: Bearer <access_token>` on `/api/auth/me` and `/api/videos*`.

## Injury-risk dashboard (v0.7.0)
Player fatigue & injury-risk prediction. Model, data, label rule, gates and the **not-medical-advice** caveat:
[`ml/README.md`](ml/README.md). Frontend contract: `sync/CONTRACT_risk.md`.

| Endpoint | What |
|---|---|
| `GET /api/roster/risk?team_id=&sort=desc\|asc&match_id=` | Team roster sorted by latest risk (unscored players last), with features + top-5 factors |
| `GET /api/players/{id}/risk` | One player's risk history, newest first |
| `POST /api/uploads/csv` | Athlete logs (multipart `file`, optional `team_id`, `dry_run`): validate, match players, encrypt HR, score |
| `GET /api/uploads/csv` / `DELETE /api/uploads/csv/{id}` | List / remove an upload (affected players are re-scored) |

Example CSV: [`docs/example_athlete_logs.csv`](docs/example_athlete_logs.csv). Every response carries
`X-Response-Time-ms`; risk endpoints also log `latency ...` lines (requirement: < 3 s; tested at 25 players x 10 matches).

**Setup on an existing install** (after the usual DB backup):

```bash
cd backend
sed '/^USE /d' migrations/010_player_risk.sql | mysql -u root soccer_analytics_app   # 3 new tables
.venv/bin/pip install -r requirements.txt                                            # scikit-learn, pandas (pinned)
# add HEALTH_DATA_KEY to .env (base64 of 32 random bytes; generate on the server, never commit/print it):
.venv/bin/python - <<'EOF'
import base64, secrets
k = base64.b64encode(secrets.token_bytes(32)).decode()
s = open('.env', 'rb').read()
open('.env', 'ab').write((b'' if s.endswith(b'\n') else b'\n') + b'HEALTH_DATA_KEY=' + k.encode() + b'\n')
EOF
.venv/bin/python gen_cert.py               # self-signed certs/cert.pem + certs/key.pem (gitignored)
.venv/bin/python -m ml.backfill_risk       # score existing stats rows
```

**HTTP (dev default) + HTTPS side by side.** HTTP stays on `127.0.0.1:8000`; HTTPS runs as a second process on
`127.0.0.1:8443` with the self-signed cert. `STARTUP_RECOVERY=false` stops the second process from marking the first
one's running jobs as failed at startup.

```bash
cd backend
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000                                   # HTTP
STARTUP_RECOVERY=false .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8443 \
    --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem                             # HTTPS
curl -k https://127.0.0.1:8443/health
# or both with the frontend:  scripts/dev.sh --https
```

Detached (survives the terminal), as used on the Mac:

```bash
cd backend && .venv/bin/python -c "import subprocess,os; subprocess.Popen(['.venv/bin/uvicorn','main:app','--host','127.0.0.1','--port','8443','--ssl-keyfile','certs/key.pem','--ssl-certfile','certs/cert.pem'], stdout=open('/tmp/soccer-backend-https.log','w'), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True, env={**os.environ,'STARTUP_RECOVERY':'false'})"
```

Browsers warn once about the self-signed cert (open `https://127.0.0.1:8443/health` and accept it before the
frontend calls it). CORS is the same on both ports.

**Security summary.** Passwords: bcrypt hashes (since v0.1). Heart rate, risk scores and the stored feature snapshot:
AES-256-GCM, random 96-bit nonce per value, `base64(nonce||ciphertext||tag)`, key `HEALTH_DATA_KEY`. If the key is
missing or malformed the server still starts (logged as an error) and the risk/CSV endpoints answer
`503 {"detail": "Health data encryption is not configured: ..."}`; ingest skips scoring. `.env`, `.env.bak-*` and
`certs/` are gitignored. Settings: `RISK_RED_THRESHOLD` (70), `RISK_YELLOW_THRESHOLD` (40), `CSV_MAX_MB` (5),
`CSV_MAX_ROWS` (5000), `STARTUP_RECOVERY` (true).

**v0.7.0 ingest fixes (from the CV Engineer):** `minutes_played` is never filled from the clip length (null when the
CV has none); `0.0` distances/speeds/minutes are values, not "missing"; accels/decels are never fabricated;
`injury_risk`/`fatigue_risk_score` are never model inputs; sprint counts never come from `hi_efforts_count`.

## ERD parity (v0.6.0)

Live `soccer_analytics_app` now has every original-ERD column (plus the app extras). See `sync/CONTRACT_erd_parity.md`: `GET/PATCH /api/players`, `video_type` / `resolution` / `duration_seconds` on videos, and dual stats naming (`distance_covered_meters`, `fatigue_risk_score`, …). Migration `009_erd_parity.sql` is idempotent.

## Player tracking (v0.5.0)

Pick one player in an uploaded (processed) video and follow them through the clip. Public contract (adopted with
the frontend 2026-10-02; `sync/CONTRACT_track_player.md`, docs/API.md): every box is **normalised** `[x, y, w, h]`
(0-1, top-left origin); frames are **0-based at the native fps**, `t = f / fps`.

1. `GET /api/videos/{id}/detections?frame=120` → the frame still (`frame_url`, works as `<img src>`) and the people
   detected on it (`player_id` when the processed video's own detections match the box, else null).
2. `POST /api/videos/{id}/tracks` with `{"frame": 120, "bbox": <a detection's bbox>}` (extra labels such as
   `player_id`, `jersey_number`, `team` are kept), or `{"player_id": 24}` (starts from that player's stored
   detection), or `{"jersey_number": 10}` (team optional) → 202 with the full track object.
3. Poll `GET /api/tracks/{track_id}` until `status` is `done` or `failed` (`error_code` `target_not_found` = the
   CV couldn't find/follow that player; pick another frame or box).
4. Play `annotated_url` in a `<video>` (HTTP Range works, so seeking works), or play the original via the video's
   `source_url` and draw `GET frames_url` boxes on a canvas (`state`: tracked, occluded = interpolated estimate,
   lost = bbox null).
   `summary` (v0.5.1 definitions): `lost_segments` = inclusive `[first, last]` frame runs with state lost;
   `reacquisition_count` = recovery EVENTS, one per lost segment whose next non-occluded frame is tracked (a
   lost/occluded gap that ends tracked counts once; a trailing lost segment counts 0), never a frame count;
   `coverage_pct` = (tracked + occluded) / frame_count. Real mode prefers the CV's own `meta.json` values when valid.

Mode: `TRACK_PIPELINE_MODE` (see the settings table), independent of `CV_PIPELINE_MODE`. Real mode runs the CV
interface documented at the top of `tracking.py` (`python -m cv.detect_frame ...`, `python -m cv.track_player ...`,
pixel boxes, exit code 3 = target not found), owned by the CV pipeline; the backend converts to the public shapes.
The stub uses the video's stored detections for the requested frame when it has any (else 10-14 fake boxes), fakes a
smooth track with occluded/lost gaps, and renders a real annotated MP4 with ffmpeg (H.264, yuv420p, `+faststart`,
same fps and frame count as the source), marked `source: "stub"` with a warning. One active track per video;
tracks interrupted by a restart are marked failed.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q   # 164 tests, about 65 s (ffmpeg needed for the tracking tests); includes a fake cv/run_pipeline.py contract test and an end-to-end
                                # upload -> stub processing -> stats/heatmap/tags/insights/results flow (tests/test_e2e_flow.py)
```

The suite can't touch your real data. `tests/conftest.py` skips `backend/.env` (`BACKEND_ENV_FILE=""`), forces
`DATABASE_URL` to a SQLite file in a fresh temp dir and points every upload/thumbnail/CV output dir there. It also
disables the MySQL drivers (any connect attempt raises), aborts before seeding if any of that doesn't hold, and
fails the run if `backend/uploads/` changed. `tests/test_isolation.py` asserts all of this.

## Schema notes

- `schema.sql` = full current schema (fresh installs). `migrations/000..008` = deltas for existing DBs
  (003 adds `match_videos.stage`, `progress`, `thumbnail_path` and backfills stage/progress from status; 004 adds
  `metric_definitions`, `player_match_metrics`, `player_heatmaps`; 005 adds match scores/`our_side`/`result` and the tag
  tables; 006 adds `player_heatmaps.source`/`cell_unit` and refreshes the metric definitions for CV v1.2.0; 007 adds
  `video_player_overrides` and refreshes the definitions again: minutes now 2 decimals; 008 adds `player_tracks`).
  Keep both in sync with `models.py`.
- Video status enum is now `queued/processing/done/failed` (the migration maps `pending→queued`, `completed→done`).
- `player_match_stats.video_id` is NULL for legacy/manual rows (e.g. everything that existed before migration 002,
  and seeded match-2 rows). Seeded match-1 rows belong to sample video 1. Deleting a video deletes its stats.
- Deleting a user cascades to their teams, matches, and videos; deleting a player sets
  `tracking_detections.player_id` to NULL.
