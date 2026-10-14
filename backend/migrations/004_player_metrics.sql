-- Migration 004: extended per-player metrics (key-value) + heatmaps.
-- Run AFTER 001, 002, 003. Fresh installs don't need it (schema.sql has everything).
-- Usage (from backend/):  mysql -u root -p < migrations/004_player_metrics.sql
-- Idempotent: safe to run more than once (MySQL 8+ and MariaDB). Definitions are upserted (re-run to refresh).
-- Design: docs/metrics-extension-plan.md. Source of truth for the definitions: metrics_catalog.py.

USE soccer_analytics_app;

-- FK columns get the same type as the key they reference: 'int' (schema.sql) or 'int unsigned' (original ERD).
SET @stat_type = (SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_stats' AND COLUMN_NAME = 'stat_id');

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

-- player_heatmaps: grid_cols = along the pitch length (pitch_x): 21 pipeline / 12 backend; grid_rows = across the
-- width (pitch_y): 14 pipeline / 8 backend; samples = detections behind the grid; cells = JSON [[value x cols] x rows],
-- row 0 = pitch_y 0; source = pipeline (heatmaps.json) | backend (from detections); cell_unit = seconds | samples.
-- player_match_metrics.value NULL = computed but unavailable (e.g. no calibration).
SET @sql = CONCAT('CREATE TABLE IF NOT EXISTS player_match_metrics (
  stat_id     ', @stat_type, '         NOT NULL,
  metric_key  VARCHAR(64) NOT NULL,
  value       DOUBLE      NULL,
  PRIMARY KEY (stat_id, metric_key),
  KEY ix_pmm_metric_value (metric_key, value),
  CONSTRAINT fk_pmm_stat   FOREIGN KEY (stat_id)    REFERENCES player_match_stats (stat_id)
    ON DELETE CASCADE,
  CONSTRAINT fk_pmm_metric FOREIGN KEY (metric_key) REFERENCES metric_definitions (metric_key)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = CONCAT('CREATE TABLE IF NOT EXISTS player_heatmaps (
  stat_id         ', @stat_type, '     NOT NULL,
  grid_cols       INT     NOT NULL,
  grid_rows       INT     NOT NULL,
  pitch_length_m  DOUBLE  NOT NULL,
  pitch_width_m   DOUBLE  NOT NULL,
  samples         INT     NOT NULL,
  cells           TEXT    NOT NULL,
  source          VARCHAR(10) NOT NULL DEFAULT ''backend'',
  cell_unit       VARCHAR(10) NOT NULL DEFAULT ''samples'',
  PRIMARY KEY (stat_id),
  CONSTRAINT fk_heatmap_stat FOREIGN KEY (stat_id) REFERENCES player_match_stats (stat_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

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


SELECT 'migration 004_player_metrics applied' AS status;
