-- Migration 006: CV pipeline v1.2.0 fields.
-- Run AFTER 001-005. Fresh installs don't need it (schema.sql has everything).
-- Usage (from backend/):  mysql -u root -p < migrations/006_pipeline_v120.sql
-- Idempotent: safe to run more than once (MySQL 8+ and MariaDB).
--  * player_heatmaps.source / cell_unit (pipeline heatmaps.json grids are 21x14 seconds; backend fallback 12x8 counts)
--  * metric definitions refreshed/added: top_speed_kmh, visible_minutes, coverage_pct, hsr_count; zones, accels,
--    decels, high_intensity_efforts are now 'ready'. (The API also upserts these at startup.)
-- New per-player values need no columns: they are rows in player_match_metrics.

USE soccer_analytics_app;

SET @db = DATABASE();

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db
               AND TABLE_NAME = 'player_heatmaps' AND COLUMN_NAME = 'source') = 0,
  'ALTER TABLE player_heatmaps ADD COLUMN source VARCHAR(10) NOT NULL DEFAULT ''backend''',
  'SELECT ''source exists'' AS info');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db
               AND TABLE_NAME = 'player_heatmaps' AND COLUMN_NAME = 'cell_unit') = 0,
  'ALTER TABLE player_heatmaps ADD COLUMN cell_unit VARCHAR(10) NOT NULL DEFAULT ''samples''',
  'SELECT ''cell_unit exists'' AS info');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

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

SELECT 'migration 006_pipeline_v120 applied' AS status;
