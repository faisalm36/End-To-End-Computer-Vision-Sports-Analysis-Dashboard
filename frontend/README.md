# Soccer Analytics: frontend

This is the web client for the soccer video analytics capstone. Coaches sign up, upload match video, tag
each match with its conditions (weather, pitch and so on) plus a score, and follow the processing
pipeline. When processing finishes they get per-player telemetry (distance, speed, workload, tracking
coverage and a positional heatmap) and condition-based insights across matches. All data comes from the
FastAPI backend (`capstone-backend`, v0.4.0).

## Stack

- React 19 and React Router 8 (`react-router`)
- Vite 8 (dev server and build), Tailwind CSS v4 (`@tailwindcss/vite`)
- oxlint for linting
- Vitest 5, React Testing Library, user-event, jest-dom and jsdom for tests

## Setup

Node **≥ 22.22** is recommended. React Router 8.4 declares `engines.node >= 22.22.0`. On Node 22.14,
`npm install` prints an `EBADENGINE` warning, but dev, build, lint and test all work. jsdom is pinned to
29 because jsdom 30 needs Node ≥ 22.22.2.

```bash
cd frontend
cp .env.example .env      # then edit if the backend is not on localhost:8000
npm install
npm run dev               # http://localhost:5173
```

### Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `VITE_API_URL` | `http://localhost:8000` | Base URL of the FastAPI backend, with no trailing slash. |
| `VITE_MAX_UPLOAD_MB` | unset | A fallback upload limit only. The real limit and the allowed file types come from `GET /api/config` at runtime. This value applies only if that call fails. |

### Scripts

| Command | What it does |
| --- | --- |
| `npm run dev` | Vite dev server on **port 5173** with `strictPort`. The backend's CORS allow-list expects this origin, so Vite fails instead of silently moving to 5174. |
| `npm run build` | Production build to `dist/`. |
| `npm run preview` | Serves the built `dist/`. |
| `npm run lint` | oxlint (`.oxlintrc.json`). |
| `npm test` | `vitest run`, all tests once (jsdom). |
| `npm run test:watch` | Vitest in watch mode. |

The test config lives in the `test` block of `vite.config.js`. Tests use `src/test/setup.js`, and the
files match `src/**/*.test.{js,jsx}`. `fetch` and XHR are mocked with `src/test/mockApi.js`, so no
backend is needed. Some fixtures in `src/test/fixtures/` were captured from the real backend.

## Routes

| Path | Access | Page |
| --- | --- | --- |
| `/` | public | Landing |
| `/login`, `/signup`, `/forgot-password` | public | Auth pages |
| `/dashboard` | public | Squad telemetry from `GET /api/players/stats`. Uses sample players if that fails. |
| `/upload` | signed in | Upload a match video with tags, side and score, then follow processing |
| `/profile` | signed in | Upload history with the tag filter (OR/AND), plus account settings |
| `/history` | signed in | Redirects to `/profile` |
| `/videos/:id` | signed in | Processing status, then results (telemetry, heatmap, tags, score) |
| `/players` | signed in | Squad roster by team; edit name, jersey, position, foot, contract end (v0.6.0) |
| `/insights` | signed in | Insights by tag key (e.g. weather) and the next-match comparison |
| `/videos/:id/track` | signed in | Track a player: pick a player on a frame (or by shirt number), follow progress |
| `/videos/:id/track/:trackId` | signed in | Progress, then the replay of that track (deep-linkable) |
| `*` | public | Not found |

Protected routes redirect to `/login` and return to the requested page after sign-in. A 401 from the API
ends the session, except on the login form itself, where it shows as an inline error.

## Project structure

```
src/
  App.jsx, main.jsx      routes and entry point
  Dashboard.jsx          squad telemetry (table, leaderboards, player detail, heatmap)
  pages/                 one component per route
  components/            layout, nav, form fields, tags, progress stepper, score, shared UI
  auth/                  AuthProvider, ProtectedRoute, useAuth
  lib/                   API client and pure helpers (stats normalisation, metrics registry,
                         tags, insights, validation, upload config, sample data)
  theme.css, index.css   design tokens and global styles
  test/                  test setup, API mocks, render helper, fixtures
  __tests__/             test suites
```

## Backend endpoints used

All paths are relative to `VITE_API_URL` and use bearer-token auth unless noted. See `src/lib/api.js`.

- Auth: `POST /api/auth/login` and `POST /api/auth/register` (no auth), `GET/PATCH /api/auth/me`, and
  `POST /api/auth/change-password`
- `GET /api/config` (no auth): upload limit and allowed types
- Videos:
  - `GET /api/videos` and `GET /api/videos?tag=key:value`
  - `POST /api/videos` (multipart upload via XHR, for progress)
  - `GET /api/videos/{id}` and `DELETE /api/videos/{id}`
  - `GET /api/videos/{id}/stats`
  - `PUT /api/videos/{id}/tags`
  - each video's `thumbnail_url`, a relative self-tokened URL resolved against `VITE_API_URL`
- Matches: `GET /api/matches` (with `?tag=`), `GET /api/matches/{id}`, and `PATCH /api/matches/{id}` for
  the score
- `GET /api/tags`: tag keys and values for suggestions and filters. If it fails, the app builds them
  from the video list.
- `GET /api/insights?tag_key=…` (optional `player_id`). On 404 the app computes insights from the videos
  instead.
- `GET /api/metrics` (no auth): the metric registry (labels, units, `availability`, `decimals`,
  `is_estimate`)
- `PATCH /api/videos/{id}/players/{player_id}` `{jersey_number}`: jersey corrections. 409/422 show inline;
  404/405/503 or a network error fall back to a correction saved in this browser, with a note.
- Track a player (backend v0.5.0; `src/lib/api.js`, with shapes normalised in `src/lib/tracking.js`):
  - `GET /api/videos/{id}/detections?frame=N` (boxes for pick mode) and `GET /api/videos/{id}/frame?frame=N` (JPEG)
  - `POST /api/videos/{id}/tracks` → 202 with the track (409 `{track_id}` while one is running) and
    `GET /api/videos/{id}/tracks`
  - `GET/DELETE /api/tracks/{id}`, `GET /api/tracks/{id}/frames?start&end` (dense, `tracked|occluded|lost`)
  - `GET /api/tracks/{id}/annotated.mp4` and `video.source_url` (`/api/videos/{id}/source`), both with Range
  - Boxes are `[x, y, w, h]` normalised 0–1. Servers without these routes (404) or not migrated (503) show
    "Player tracking isn't available on this server yet".
- `GET /api/players` and `PATCH /api/players/{id}` (Players page, v0.6.0). Older backends without them show "not available yet".
- Upload form field `video_type` (`tactical_cam` | `broadcast` | `endzone_cam`; default `tactical_cam`). Video objects expose `video_type`, `resolution`, `duration_seconds`.
- Stats dual names (v0.6.0): `distance_covered_meters`, `fatigue_risk_score` (0/50/100), `minutes_played`, `sprint_count`, alongside mph / km / `injury_risk`. Insights add `avg_distance_covered_meters`, `avg_top_speed_kmh`, `avg_sprint_count`, `avg_fatigue_risk_score`.
- `GET /api/players/stats` (dashboard). `getPlayerMetrics` (`GET /api/players/{id}/metrics`) exists in
  the client but no page calls it yet.

## Design system notes

The tokens are in `src/theme.css` (Tailwind v4 `@theme`):

- **Dark surfaces.** Elevation comes from lightness, not shadow: `surface-base`, `sunken`, `raised`,
  `overlay` and `selected`, with `line`/`line-strong`/`line-input` borders.
- **Text.** Small text is never lighter than `fg-muted` (slate-400). `fg-disabled` is for disabled
  states only.
- **Accent.** `--color-accent` (lime `#bef264`) is a single swappable token, and the hover, muted and
  glow values are derived from it. It is for UI chrome only (buttons, focus rings, active nav) and is
  never used to encode data.
- **Tracked-player box.** The replay draws the tracked player's box in the accent lime (per the Track-a-player
  UI/UX spec); it reads clearly against the green pitch. Dashed = estimate (occluded/interpolated) or confidence
  under 0.5. Lost frames are slate diagonal stripes on the timeline, not amber/red.
- **Metric colours.** `metric-speed` (cyan) and `metric-distance` (violet) encode data. `squad-avg` is
  the average tick.
- **Green, amber and red** (`risk-*`, `status-*`) are reserved for workload and status: workload bands,
  success, warnings (e.g. low tracking coverage) and errors. "Unknown" is a first-class grey state.
- **Tag chips** are neutral and never use risk colours.
- **Missing values** show as "—". Metrics the registry marks as not yet available show "Coming soon".
  Video-derived metrics carry an "Estimated from video" badge when the registry says `is_estimate`.

## Sample / demo mode

If the backend can't be reached, the login page offers **"Explore with sample data"**. This starts a
local demo session (no token is sent to the backend) and the pages show labelled sample data. In demo
mode uploads are simulated and nothing leaves the device. Track a player in demo mode uses a synthetic
sample in `public/sample/track-demo*` (250 frames, 25 fps); the simulated track always follows red #10, and the
page says so. `/dashboard` also falls back to sample players, with a notice, if
`/api/players/stats` fails.

## Known limitations

- **Stub pipeline.** With the backend's `CV_PIPELINE_MODE=stub`, stages and stats are synthetic. Stub
  rows can have `minutes_played` of 0, which would give absurd per-minute rates, so the UI hides
  distance/min when tracked minutes are under 1 or the rate is above 300 m/min.
- **Jersey corrections** are saved with `PATCH /api/videos/{id}/players/{player_id}`. Servers without that
  endpoint (v0.4.0) get a correction stored in `localStorage` for this browser, and the UI says so.
- **Track a player:** when a video's `source_url` is null (the original file is gone), "Live overlay" is disabled
  with the reason and only "Annotated video" plays. There is no re-anchoring / "wrong player" correction (no
  endpoint). Servers without tracking routes (e.g. v0.4.0) show "Player tracking isn't available on this server
  yet". Stub-mode tracks (`source: "stub"`) carry a "Stub track" banner.
- **No retry-from-step.** A failed processing step shows the error and a "Report issue" link. That link
  is a placeholder `mailto:support@example.com`. To retry, re-upload.
- **`minutes_played` is the video length, not time on the pitch.** Time actually tracked comes from
  `visible_minutes` and `coverage_pct`. The UI shows these as "Tracked N% of match" and warns below 60%.
- **Speed thresholds** are shown from the stats rows' `speed_thresholds`. Older or seeded videos without
  them are labelled "Default speed thresholds (not reported for this video)".
- Tags belong to the match, so they stay on the match after its video is deleted.
- The insights `delta_vs_baseline`, `change_pct_vs_baseline` and per-group `metrics` fields are not used
  by the UI yet.
