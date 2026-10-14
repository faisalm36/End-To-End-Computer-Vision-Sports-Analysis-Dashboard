-- Soccer Video Analytics - MySQL 8 schema
-- Usage (from backend/):  mysql -u root -p < schema.sql
-- Keep in sync with models.py. Safe to re-run (IF NOT EXISTS everywhere).
-- Existing DB created from an older version? Run migrations/000 ... 009 (in order) instead.

CREATE DATABASE IF NOT EXISTS soccer_analytics_app
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE soccer_analytics_app;

CREATE TABLE IF NOT EXISTS users (
  user_id        INT          NOT NULL AUTO_INCREMENT,
  first_name     VARCHAR(50)  NOT NULL,
  last_name      VARCHAR(50)  NOT NULL,
  email          VARCHAR(255) NOT NULL,
  password_hash  VARCHAR(255) NOT NULL,
  role           VARCHAR(20)  NOT NULL DEFAULT 'analyst',
  created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id),
  UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS teams (
  team_id    INT          NOT NULL AUTO_INCREMENT,
  user_id    INT          NOT NULL,
  team_name  VARCHAR(100) NOT NULL,
  league     VARCHAR(100) NULL,
  created_at TIMESTAMP    NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (team_id),
  KEY ix_teams_user_id (user_id),
  CONSTRAINT fk_teams_user FOREIGN KEY (user_id)
    REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS players (
  player_id          INT          NOT NULL AUTO_INCREMENT,
  team_id            INT          NOT NULL,
  first_name         VARCHAR(50)  NOT NULL,
  last_name          VARCHAR(50)  NOT NULL,
  jersey_number      INT          NULL,
  position           VARCHAR(30)  NULL,
  dominant_foot      ENUM('Left','Right','Both') NULL,
  contract_end_date  DATE         NULL,
  created_at         TIMESTAMP    NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (player_id),
  UNIQUE KEY uq_players_team_jersey (team_id, jersey_number),
  KEY ix_players_team_id (team_id),
  CONSTRAINT fk_players_team FOREIGN KEY (team_id)
    REFERENCES teams (team_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matches (
  match_id            INT          NOT NULL AUTO_INCREMENT,
  home_team_id        INT          NOT NULL,
  away_team_id        INT          NOT NULL,
  match_date          DATE         NOT NULL,
  stadium_name        VARCHAR(100) NULL,
  weather_condition   VARCHAR(50)  NULL,
  tactical_formation  VARCHAR(20)  NULL,
  home_score          INT          NULL,
  away_score          INT          NULL,
  our_side            ENUM('home','away') NULL,     -- which team is "yours" when you own both (NULL = home)
  result              ENUM('W','D','L') NULL,       -- from our side; derived from the score when both are set
  created_at          TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (match_id),
  KEY ix_matches_home_team_id (home_team_id),
  KEY ix_matches_away_team_id (away_team_id),
  CONSTRAINT fk_matches_home_team FOREIGN KEY (home_team_id)
    REFERENCES teams (team_id) ON DELETE CASCADE,
  CONSTRAINT fk_matches_away_team FOREIGN KEY (away_team_id)
    REFERENCES teams (team_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS match_videos (
  video_id           INT          NOT NULL AUTO_INCREMENT,
  match_id           INT          NOT NULL,
  user_id            INT          NULL,          -- uploader; always set by the API
  title              VARCHAR(255) NULL,
  file_name          VARCHAR(255) NOT NULL,     -- original upload name
  file_path          VARCHAR(500) NOT NULL,     -- stored path (uploads/<uuid>.<ext>)
  video_type         ENUM('tactical_cam','broadcast','endzone_cam') NOT NULL DEFAULT 'tactical_cam',
  fps                FLOAT        NULL,
  resolution         VARCHAR(20)  NULL,          -- e.g. 1920x1080 (from CV meta)
  duration_seconds   FLOAT        NULL,          -- from CV meta.duration_s
  processing_status  ENUM('queued','processing','done','failed') NOT NULL DEFAULT 'queued',
  stage              VARCHAR(20)  NOT NULL DEFAULT 'queued',  -- queued|detect|track|ocr|metrics|ingest|done|failed
  progress           INT          NOT NULL DEFAULT 0,          -- 0-100
  error_message      TEXT         NULL,
  thumbnail_path     VARCHAR(500) NULL,                        -- uploads/thumbnails/<video_id>.jpg
  pipeline_meta      TEXT         NULL,          -- JSON: CV meta.json + adapter info
  uploaded_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  processed_at       DATETIME     NULL,
  PRIMARY KEY (video_id),
  KEY ix_match_videos_match_id (match_id),
  KEY ix_match_videos_user_id (user_id),
  CONSTRAINT fk_match_videos_match FOREIGN KEY (match_id)
    REFERENCES matches (match_id) ON DELETE CASCADE,
  CONSTRAINT fk_match_videos_user FOREIGN KEY (user_id)
    REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS player_match_stats (
  stat_id        INT           NOT NULL AUTO_INCREMENT,
  player_id      INT           NOT NULL,
  match_id       INT           NOT NULL,
  video_id       INT           NULL,          -- NULL = legacy/manual row not tied to a processed video
  top_speed_mph            DECIMAL(5,2)  NULL,          -- NULL when the CV run had no calibration
  distance_km              DECIMAL(6,3)  NULL,
  injury_risk              ENUM('Low','Medium','High') NOT NULL DEFAULT 'Low',
  -- ERD names (v0.6.0); kept alongside mph/km/injury_risk
  distance_covered_meters  DECIMAL(7,2)  NULL,
  top_speed_kmh            DECIMAL(5,2)  NULL,
  minutes_played           FLOAT         NULL,
  sprint_count             INT           NULL,
  fatigue_risk_score       DECIMAL(5,2)  NULL,          -- 0/50/100 mapped from injury_risk
  PRIMARY KEY (stat_id),
  UNIQUE KEY uq_stats_player_video (player_id, video_id),
  KEY ix_player_match_stats_player_id (player_id),
  KEY ix_player_match_stats_match_id (match_id),
  KEY ix_player_match_stats_video_id (video_id),
  CONSTRAINT fk_stats_player FOREIGN KEY (player_id)
    REFERENCES players (player_id) ON DELETE CASCADE,
  CONSTRAINT fk_stats_match FOREIGN KEY (match_id)
    REFERENCES matches (match_id) ON DELETE CASCADE,
  CONSTRAINT fk_stats_video FOREIGN KEY (video_id)
    REFERENCES match_videos (video_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tracking_detections (
  detection_id  BIGINT  NOT NULL AUTO_INCREMENT,
  video_id      INT     NOT NULL,
  player_id     INT     NULL,          -- NULL until the track is identified (e.g. via jersey OCR)
  track_id      INT     NOT NULL,
  frame_number  INT     NOT NULL,
  object_class  VARCHAR(20) NOT NULL DEFAULT 'player',  -- 'player' | 'ball'
  jersey_number INT     NULL,          -- OCR jersey number from the CV pipeline
  bbox_x1       FLOAT   NOT NULL,
  bbox_y1       FLOAT   NOT NULL,
  bbox_x2       FLOAT   NOT NULL,
  bbox_y2       FLOAT   NOT NULL,
  -- ERD centre/size (v0.6.0); computed from corners at write time
  x_center      FLOAT   NULL,
  y_center      FLOAT   NULL,
  bbox_width    FLOAT   NULL,
  bbox_height   FLOAT   NULL,
  confidence    FLOAT   NOT NULL,
  pitch_x       FLOAT   NULL,          -- metres on the pitch after homography
  pitch_y       FLOAT   NULL,
  PRIMARY KEY (detection_id),
  KEY idx_detections_video_frame (video_id, frame_number),
  KEY ix_tracking_detections_player_id (player_id),
  CONSTRAINT fk_detections_video FOREIGN KEY (video_id)
    REFERENCES match_videos (video_id) ON DELETE CASCADE,
  CONSTRAINT fk_detections_player FOREIGN KEY (player_id)
    REFERENCES players (player_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---- metrics (migration 004) ----
CREATE TABLE IF NOT EXISTS metric_definitions (
  metric_key           VARCHAR(64)  NOT NULL,           -- = key in API "metrics" objects
  label                VARCHAR(100) NOT NULL,
  unit                 VARCHAR(20)  NULL,
  category             VARCHAR(30)  NOT NULL,           -- physical|coverage|positional|intensity|workload|speed_zone
  value_type           VARCHAR(10)  NOT NULL DEFAULT 'float',   -- float | int
  aggregation          VARCHAR(10)  NOT NULL,           -- sum | max | min | avg | ratio (multi-video rule)
  ratio_numerator      VARCHAR(64)  NULL,               -- aggregation=ratio: SUM(num) * ratio_scale / SUM(den)
  ratio_denominator    VARCHAR(64)  NULL,
  ratio_scale          DOUBLE       NOT NULL DEFAULT 1,
  decimals             INT          NOT NULL DEFAULT 2,
  higher_is_better     TINYINT(1)   NULL,
  requires_calibration TINYINT(1)   NOT NULL DEFAULT 1,
  is_estimate          TINYINT(1)   NOT NULL DEFAULT 1,
  availability         VARCHAR(10)  NOT NULL DEFAULT 'ready',   -- ready | soon (null until the pipeline emits it)
  storage              VARCHAR(10)  NOT NULL DEFAULT 'metric',  -- column (player_match_stats) | metric
  description          VARCHAR(500) NULL,
  sort_order           INT          NOT NULL DEFAULT 100,
  is_active            TINYINT(1)   NOT NULL DEFAULT 1,
  PRIMARY KEY (metric_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS player_match_metrics (
  stat_id     INT         NOT NULL,                     -- one player in one video (player_match_stats row)
  metric_key  VARCHAR(64) NOT NULL,
  value       DOUBLE      NULL,                         -- NULL = computed but unavailable (e.g. no calibration)
  PRIMARY KEY (stat_id, metric_key),
  KEY ix_pmm_metric_value (metric_key, value),
  CONSTRAINT fk_pmm_stat   FOREIGN KEY (stat_id)    REFERENCES player_match_stats (stat_id)
    ON DELETE CASCADE,
  CONSTRAINT fk_pmm_metric FOREIGN KEY (metric_key) REFERENCES metric_definitions (metric_key)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS player_heatmaps (
  stat_id         INT     NOT NULL,
  grid_cols       INT     NOT NULL,                     -- along the pitch length (pitch_x): 21 pipeline / 12 backend
  grid_rows       INT     NOT NULL,                     -- across the width (pitch_y): 14 pipeline / 8 backend
  pitch_length_m  DOUBLE  NOT NULL,
  pitch_width_m   DOUBLE  NOT NULL,
  samples         INT     NOT NULL,                     -- detections behind the grid
  cells           TEXT    NOT NULL,                     -- JSON [[value x cols] x rows], row 0 = pitch_y 0
  source          VARCHAR(10) NOT NULL DEFAULT 'backend',  -- pipeline (heatmaps.json) | backend (from detections)
  cell_unit       VARCHAR(10) NOT NULL DEFAULT 'samples',  -- seconds (pipeline) | samples (backend)
  PRIMARY KEY (stat_id),
  CONSTRAINT fk_heatmap_stat FOREIGN KEY (stat_id) REFERENCES player_match_stats (stat_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO metric_definitions
  (metric_key, label, unit, category, value_type, aggregation, ratio_numerator, ratio_denominator, ratio_scale, decimals, higher_is_better, requires_calibration, is_estimate, availability, storage, sort_order, description, is_active)
VALUES
  ('distance_km', 'Total distance', 'km', 'physical', 'float', 'sum', NULL, NULL, 1.0, 2, 1, 1, 1, 'ready', 'column', 10, 'Distance covered while tracked (smoothed). Estimated from video.', 1),
  ('top_speed_mph', 'Top speed (max sustained)', 'mph', 'physical', 'float', 'max', NULL, NULL, 1.0, 1, 1, 1, 1, 'ready', 'column', 11, 'Max sustained (~1 s rolling) speed. Estimated from video.', 1),
  ('top_speed_kmh', 'Top speed (max sustained)', 'km/h', 'physical', 'float', 'max', NULL, NULL, 1.0, 1, 1, 1, 1, 'ready', 'metric', 12, 'Same as top_speed_mph in km/h (pipeline top_speed_kmh, else mph x 1.60934).', 1),
  ('distance_per_min', 'Distance per minute', 'm/min', 'physical', 'float', 'ratio', 'distance_km', 'visible_minutes|minutes_played', 1000.0, 0, 1, 1, 1, 'ready', 'metric', 13, 'distance_km * 1000 / visible (tracked) minutes; falls back to minutes_played when visible_minutes is unknown. Pipeline v1.2 key distance_per_min_m (same definition). Cross-video: sum(distance) / sum(minutes). Null when those minutes are under 0.1 (too short to be meaningful).', 1),
  ('minutes_played', 'Minutes played (first to last seen)', 'min', 'coverage', 'float', 'sum', NULL, NULL, 1.0, 2, NULL, 0, 1, 'ready', 'metric', 14, 'Pipeline v1.2 minutes_played (first to last visible frame). Older pipelines: video length (duration_s / 60) as an estimate.', 1),
  ('visible_minutes', 'Minutes tracked', 'min', 'coverage', 'float', 'sum', NULL, NULL, 1.0, 2, NULL, 0, 1, 'ready', 'metric', 15, 'Pipeline v1.2 visible_minutes: time the player was actually tracked.', 1),
  ('coverage_pct', 'Tracking coverage', '%', 'coverage', 'float', 'avg', NULL, NULL, 1.0, 0, NULL, 0, 1, 'ready', 'metric', 16, 'Pipeline v1.2 coverage_pct: share of video frames with the player tracked (fragments of one player are added, capped at 100). Cross-video: mean.', 1),
  ('avg_pitch_x', 'Average position (x, along length)', 'm', 'positional', 'float', 'avg', NULL, NULL, 1.0, 1, NULL, 1, 1, 'ready', 'metric', 17, 'Pipeline v1.2 avg_pitch_x, else mean pitch_x of the detections.', 1),
  ('avg_pitch_y', 'Average position (y, across width)', 'm', 'positional', 'float', 'avg', NULL, NULL, 1.0, 1, NULL, 1, 1, 'ready', 'metric', 18, 'Pipeline v1.2 avg_pitch_y, else mean pitch_y of the detections.', 1),
  ('hsr_distance_km', 'High-speed running distance', 'km', 'intensity', 'float', 'sum', NULL, NULL, 1.0, 2, 1, 1, 1, 'ready', 'metric', 20, 'Pipeline key high_speed_distance_km (threshold: meta hsr_threshold_kmh).', 1),
  ('sprint_distance_km', 'Sprint distance', 'km', 'intensity', 'float', 'sum', NULL, NULL, 1.0, 2, 1, 1, 1, 'ready', 'metric', 21, 'Pipeline key sprint_distance_km (threshold: meta sprint_threshold_kmh).', 1),
  ('hsr_count', 'High-speed runs', 'count', 'intensity', 'int', 'sum', NULL, NULL, 1.0, 0, 1, 1, 1, 'ready', 'metric', 22, 'Pipeline v1.2 hsr_count: HSR bursts >= 1 s (with hysteresis).', 1),
  ('sprint_count', 'Sprints', 'count', 'intensity', 'int', 'sum', NULL, NULL, 1.0, 0, 1, 1, 1, 'ready', 'metric', 23, 'Pipeline sprint_count: sprint bursts >= 1 s (v1.1.2+).', 1),
  ('high_intensity_efforts', 'High-intensity efforts', 'count', 'intensity', 'int', 'sum', NULL, NULL, 1.0, 0, 1, 1, 1, 'ready', 'metric', 24, 'Pipeline v1.2 hi_efforts_count (= hsr_count + sprint_count).', 1),
  ('accels', 'High accelerations (estimate)', 'count', 'workload', 'int', 'sum', NULL, NULL, 1.0, 0, 1, 1, 1, 'ready', 'metric', 30, 'Pipeline v1.2 accel_count_high (>= 3 m/s2 for >= 0.7 s). Low confidence on single-camera video.', 1),
  ('decels', 'High decelerations (estimate)', 'count', 'workload', 'int', 'sum', NULL, NULL, 1.0, 0, 1, 1, 1, 'ready', 'metric', 31, 'Pipeline v1.2 decel_count_high (<= -3 m/s2 for >= 0.7 s). Low confidence on single-camera video.', 1),
  ('zone1_distance_km', 'Distance: walk zone', 'km', 'speed_zone', 'float', 'sum', NULL, NULL, 1.0, 2, NULL, 1, 1, 'ready', 'metric', 40, 'Pipeline zone_walk_km (0 - walk edge).', 1),
  ('zone2_distance_km', 'Distance: jog zone', 'km', 'speed_zone', 'float', 'sum', NULL, NULL, 1.0, 2, NULL, 1, 1, 'ready', 'metric', 41, 'Pipeline zone_jog_km (walk - jog edge).', 1),
  ('zone3_distance_km', 'Distance: run zone', 'km', 'speed_zone', 'float', 'sum', NULL, NULL, 1.0, 2, 1, 1, 1, 'ready', 'metric', 42, 'Pipeline zone_run_km (jog - run edge).', 1),
  ('zone4_distance_km', 'Distance: high-speed zone', 'km', 'speed_zone', 'float', 'sum', NULL, NULL, 1.0, 2, 1, 1, 1, 'ready', 'metric', 43, 'Pipeline zone_hsr_km (run - hsr edge).', 1),
  ('zone5_distance_km', 'Distance: sprint zone', 'km', 'speed_zone', 'float', 'sum', NULL, NULL, 1.0, 2, 1, 1, 1, 'ready', 'metric', 44, 'Pipeline zone_sprint_km (above the hsr edge).', 1)
ON DUPLICATE KEY UPDATE
  label = VALUES(label),
  unit = VALUES(unit),
  category = VALUES(category),
  value_type = VALUES(value_type),
  aggregation = VALUES(aggregation),
  ratio_numerator = VALUES(ratio_numerator),
  ratio_denominator = VALUES(ratio_denominator),
  ratio_scale = VALUES(ratio_scale),
  decimals = VALUES(decimals),
  higher_is_better = VALUES(higher_is_better),
  requires_calibration = VALUES(requires_calibration),
  is_estimate = VALUES(is_estimate),
  availability = VALUES(availability),
  storage = VALUES(storage),
  sort_order = VALUES(sort_order),
  description = VALUES(description),
  is_active = VALUES(is_active);


-- ---- tags (migration 005) ----
CREATE TABLE IF NOT EXISTS tag_keys (
  tag_key_id  INT          NOT NULL AUTO_INCREMENT,
  user_id     INT          NOT NULL,
  name        VARCHAR(50)  NOT NULL,                    -- normalized: lower-case, no ':'
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (tag_key_id),
  UNIQUE KEY uq_tag_keys_user_name (user_id, name),
  KEY ix_tag_keys_user_id (user_id),
  CONSTRAINT fk_tag_keys_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tag_values (
  tag_value_id  INT          NOT NULL AUTO_INCREMENT,
  tag_key_id    INT          NOT NULL,
  value         VARCHAR(100) NOT NULL,                  -- case-insensitive unique per key (collation)
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (tag_value_id),
  UNIQUE KEY uq_tag_values_key_value (tag_key_id, value),
  KEY ix_tag_values_tag_key_id (tag_key_id),
  CONSTRAINT fk_tag_values_key FOREIGN KEY (tag_key_id) REFERENCES tag_keys (tag_key_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS match_tags (
  match_id      INT      NOT NULL,
  tag_value_id  INT      NOT NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (match_id, tag_value_id),
  KEY ix_match_tags_tag_value_id (tag_value_id),
  CONSTRAINT fk_match_tags_match FOREIGN KEY (match_id) REFERENCES matches (match_id) ON DELETE CASCADE,
  CONSTRAINT fk_match_tags_value FOREIGN KEY (tag_value_id) REFERENCES tag_values (tag_value_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---- per-video player corrections (migration 007) ----
-- jersey_number for a player IN ONE VIDEO (NULL = no number there); overrides players.jersey_number in that video's
-- stats only (PATCH /api/videos/{id}/players/{player_id}).
CREATE TABLE IF NOT EXISTS video_player_overrides (
  video_id       INT      NOT NULL,
  player_id      INT      NOT NULL,
  jersey_number  INT      NULL,
  updated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (video_id, player_id),
  KEY ix_video_player_overrides_player_id (player_id),
  CONSTRAINT fk_vpo_video FOREIGN KEY (video_id) REFERENCES match_videos (video_id) ON DELETE CASCADE,
  CONSTRAINT fk_vpo_player FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---- player tracks (migration 008) ----
-- One "follow this player through the clip" track per row (POST /api/videos/{id}/tracks). Target = a box on one
-- frame ('bbox'), an app player ('player') or a shirt number ('jersey'). Files: CV_OUTPUT_DIR/track_<track_id>/.
CREATE TABLE IF NOT EXISTS player_tracks (
  track_id       INT          NOT NULL AUTO_INCREMENT,
  video_id       INT          NOT NULL,
  user_id        INT          NOT NULL,
  target_mode    VARCHAR(10)  NOT NULL,                    -- bbox | player | jersey
  init_frame     INT          NULL,                        -- 0-based frame at the native fps
  init_t         FLOAT        NULL,
  bbox_x         FLOAT        NULL,                        -- normalised 0-1 [x, y, w, h], top-left origin
  bbox_y         FLOAT        NULL,
  bbox_w         FLOAT        NULL,
  bbox_h         FLOAT        NULL,
  player_id      INT          NULL,
  jersey_number  INT          NULL,
  team           VARCHAR(1)   NULL,                        -- A | B
  fps            FLOAT        NULL,                        -- source video geometry
  frame_count    INT          NULL,
  width          INT          NULL,
  height         INT          NULL,
  status         ENUM('queued','processing','done','failed') NOT NULL DEFAULT 'queued',
  stage          VARCHAR(20)  NOT NULL DEFAULT 'queued',   -- queued|detect|tracking|rendering|done|failed
  progress       INT          NOT NULL DEFAULT 0,          -- 0-100
  error_message  TEXT         NULL,
  output_dir     VARCHAR(500) NULL,
  frames_path    VARCHAR(500) NULL,
  annotated_path VARCHAR(500) NULL,
  meta           TEXT         NULL,                        -- JSON: CV meta.json + summary + adapter info
  stats          TEXT         NULL,                        -- JSON: target_stats.json or NULL
  created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  finished_at    DATETIME     NULL,
  PRIMARY KEY (track_id),
  KEY ix_player_tracks_video_status (video_id, status),
  KEY ix_player_tracks_user_id (user_id),
  KEY ix_player_tracks_player_id (player_id),
  CONSTRAINT fk_pt_video FOREIGN KEY (video_id) REFERENCES match_videos (video_id) ON DELETE CASCADE,
  CONSTRAINT fk_pt_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
  CONSTRAINT fk_pt_player FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- v0.7.0 injury-risk model (migration 010). *_enc columns = AES-256-GCM base64(nonce||ciphertext).
CREATE TABLE IF NOT EXISTS csv_uploads (
  upload_id      INT          NOT NULL AUTO_INCREMENT,
  user_id        INT NOT NULL,
  team_id        INT NULL,
  filename       VARCHAR(255) NOT NULL,
  rows_total     INT          NOT NULL DEFAULT 0,
  rows_valid     INT          NOT NULL DEFAULT 0,
  rows_invalid   INT          NOT NULL DEFAULT 0,
  rows_unmatched INT          NOT NULL DEFAULT 0,
  created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (upload_id),
  KEY ix_csv_uploads_user_id (user_id),
  CONSTRAINT fk_csvu_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
  CONSTRAINT fk_csvu_team FOREIGN KEY (team_id) REFERENCES teams (team_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS athlete_logs (
  log_id             INT     NOT NULL AUTO_INCREMENT,
  upload_id          INT     NOT NULL,
  player_id          INT NOT NULL,
  log_date           DATE    NOT NULL,
  source_row         INT     NOT NULL,
  gps_distance_km    FLOAT   NULL,
  minutes_played     FLOAT   NULL,
  sprints            INT     NULL,
  top_speed_kmh      FLOAT   NULL,
  heart_rate_enc     TEXT    NULL,
  heart_rate_max_enc TEXT    NULL,
  created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (log_id),
  KEY ix_athlete_logs_upload_id (upload_id),
  KEY ix_athlete_logs_player_date (player_id, log_date),
  CONSTRAINT fk_al_upload FOREIGN KEY (upload_id) REFERENCES csv_uploads (upload_id) ON DELETE CASCADE,
  CONSTRAINT fk_al_player FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS player_match_risk (
  risk_id          INT          NOT NULL AUTO_INCREMENT,
  player_id        INT NOT NULL,
  source           VARCHAR(10)  NOT NULL,
  stat_id          INT NULL,
  log_id           INT          NULL,
  match_id         INT NULL,
  video_id         INT NULL,
  score_date       DATE         NULL,
  risk_percent_enc TEXT         NULL,
  level            VARCHAR(10)  NOT NULL DEFAULT 'unknown',
  score_status     VARCHAR(20)  NOT NULL DEFAULT 'scored',
  score_note       VARCHAR(255) NULL,
  data_quality     VARCHAR(12)  NULL,
  model_version    VARCHAR(40)  NOT NULL,
  details_enc      TEXT         NULL,
  computed_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (risk_id),
  UNIQUE KEY uq_pmr_stat (stat_id),
  UNIQUE KEY uq_pmr_log (log_id),
  KEY ix_pmr_player_date (player_id, score_date),
  KEY ix_pmr_match_id (match_id),
  KEY ix_pmr_video_id (video_id),
  CONSTRAINT fk_pmr_player FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE,
  CONSTRAINT fk_pmr_stat FOREIGN KEY (stat_id) REFERENCES player_match_stats (stat_id) ON DELETE CASCADE,
  CONSTRAINT fk_pmr_log FOREIGN KEY (log_id) REFERENCES athlete_logs (log_id) ON DELETE CASCADE,
  CONSTRAINT fk_pmr_match FOREIGN KEY (match_id) REFERENCES matches (match_id) ON DELETE CASCADE,
  CONSTRAINT fk_pmr_video FOREIGN KEY (video_id) REFERENCES match_videos (video_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
