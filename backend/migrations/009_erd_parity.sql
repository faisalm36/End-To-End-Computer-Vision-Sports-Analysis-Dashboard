-- Migration 009: ERD parity on soccer_analytics_app.
-- Adds every column the original ER diagram had that the live app DB was missing, WITHOUT dropping or
-- renaming anything the app already has (home_score, bbox_x1..y2, injury_risk, title, …).
-- Run AFTER 001-008. Fresh installs don't need it (schema.sql has everything).
-- Usage (from backend/):  mysql -u root -p < migrations/009_erd_parity.sql
--   or:  sed '/^USE /d' migrations/009_erd_parity.sql | mysql -u root soccer_analytics_app
-- Idempotent. Drops nothing. Copies referenced key types from existing columns where relevant.
-- Backfills tracking centre/size from bbox corners, and ERD stats from mph/km + player_match_metrics.

USE soccer_analytics_app;

-- ================================================================ teams.created_at
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'teams' AND COLUMN_NAME = 'created_at') = 0,
  'ALTER TABLE teams ADD COLUMN created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP',
  'SELECT ''teams.created_at exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ================================================================ matches.created_at
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'matches' AND COLUMN_NAME = 'created_at') = 0,
  'ALTER TABLE matches ADD COLUMN created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP',
  'SELECT ''matches.created_at exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ================================================================ players.created_at, contract_end_date
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'players' AND COLUMN_NAME = 'created_at') = 0,
  'ALTER TABLE players ADD COLUMN created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP',
  'SELECT ''players.created_at exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'players' AND COLUMN_NAME = 'contract_end_date') = 0,
  'ALTER TABLE players ADD COLUMN contract_end_date DATE NULL',
  'SELECT ''players.contract_end_date exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ================================================================ match_videos: video_type, resolution, duration_seconds
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos' AND COLUMN_NAME = 'video_type') = 0,
  'ALTER TABLE match_videos ADD COLUMN video_type ENUM(''tactical_cam'',''broadcast'',''endzone_cam'') NOT NULL DEFAULT ''tactical_cam''',
  'SELECT ''match_videos.video_type exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos' AND COLUMN_NAME = 'resolution') = 0,
  'ALTER TABLE match_videos ADD COLUMN resolution VARCHAR(20) NULL',
  'SELECT ''match_videos.resolution exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos' AND COLUMN_NAME = 'duration_seconds') = 0,
  'ALTER TABLE match_videos ADD COLUMN duration_seconds FLOAT NULL',
  'SELECT ''match_videos.duration_seconds exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Backfill duration_seconds from pipeline_meta.duration_s when the column is still NULL (MySQL 8 JSON).
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos'
                 AND COLUMN_NAME IN ('duration_seconds','pipeline_meta')) = 2,
  'UPDATE match_videos
      SET duration_seconds = CAST(JSON_UNQUOTE(JSON_EXTRACT(pipeline_meta, ''$.duration_s'')) AS FLOAT)
    WHERE duration_seconds IS NULL
      AND pipeline_meta IS NOT NULL
      AND JSON_EXTRACT(pipeline_meta, ''$.duration_s'') IS NOT NULL
      AND JSON_TYPE(JSON_EXTRACT(pipeline_meta, ''$.duration_s'')) IN (''INTEGER'',''DOUBLE'',''DECIMAL'')',
  'SELECT ''no duration backfill''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Backfill resolution from pipeline_meta.resolution ("1920x1080" or [1920,1080]).
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos'
                 AND COLUMN_NAME IN ('resolution','pipeline_meta')) = 2,
  'UPDATE match_videos
      SET resolution = CASE
        WHEN JSON_TYPE(JSON_EXTRACT(pipeline_meta, ''$.resolution'')) = ''STRING''
          THEN LEFT(JSON_UNQUOTE(JSON_EXTRACT(pipeline_meta, ''$.resolution'')), 20)
        WHEN JSON_TYPE(JSON_EXTRACT(pipeline_meta, ''$.resolution'')) = ''ARRAY''
          THEN LEFT(CONCAT(JSON_UNQUOTE(JSON_EXTRACT(pipeline_meta, ''$.resolution[0]'')), ''x'',
                           JSON_UNQUOTE(JSON_EXTRACT(pipeline_meta, ''$.resolution[1]''))), 20)
        ELSE resolution END
    WHERE resolution IS NULL AND pipeline_meta IS NOT NULL
      AND JSON_EXTRACT(pipeline_meta, ''$.resolution'') IS NOT NULL',
  'SELECT ''no resolution backfill''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ================================================================ tracking_detections: centre / size (from corners)
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tracking_detections' AND COLUMN_NAME = 'x_center') = 0,
  'ALTER TABLE tracking_detections
     ADD COLUMN x_center FLOAT NULL,
     ADD COLUMN y_center FLOAT NULL,
     ADD COLUMN bbox_width FLOAT NULL,
     ADD COLUMN bbox_height FLOAT NULL',
  'SELECT ''tracking centre/size exist''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

UPDATE tracking_detections
   SET x_center    = (bbox_x1 + bbox_x2) / 2,
       y_center    = (bbox_y1 + bbox_y2) / 2,
       bbox_width  = ABS(bbox_x2 - bbox_x1),
       bbox_height = ABS(bbox_y2 - bbox_y1)
 WHERE x_center IS NULL OR y_center IS NULL OR bbox_width IS NULL OR bbox_height IS NULL;

-- ================================================================ player_match_stats: ERD columns
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_stats'
                 AND COLUMN_NAME = 'distance_covered_meters') = 0,
  'ALTER TABLE player_match_stats ADD COLUMN distance_covered_meters DECIMAL(7,2) NULL',
  'SELECT ''distance_covered_meters exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_stats'
                 AND COLUMN_NAME = 'top_speed_kmh') = 0,
  'ALTER TABLE player_match_stats ADD COLUMN top_speed_kmh DECIMAL(5,2) NULL',
  'SELECT ''top_speed_kmh exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_stats'
                 AND COLUMN_NAME = 'minutes_played') = 0,
  'ALTER TABLE player_match_stats ADD COLUMN minutes_played FLOAT NULL',
  'SELECT ''minutes_played exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_stats'
                 AND COLUMN_NAME = 'sprint_count') = 0,
  'ALTER TABLE player_match_stats ADD COLUMN sprint_count INT NULL',
  'SELECT ''sprint_count exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_stats'
                 AND COLUMN_NAME = 'fatigue_risk_score') = 0,
  'ALTER TABLE player_match_stats ADD COLUMN fatigue_risk_score DECIMAL(5,2) NULL',
  'SELECT ''fatigue_risk_score exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Backfill from imperial / categorical columns (only fills NULLs).
UPDATE player_match_stats
   SET distance_covered_meters = IF(distance_covered_meters IS NULL AND distance_km IS NOT NULL,
                                    ROUND(distance_km * 1000, 2), distance_covered_meters),
       top_speed_kmh           = IF(top_speed_kmh IS NULL AND top_speed_mph IS NOT NULL,
                                    ROUND(top_speed_mph * 1.609344, 2), top_speed_kmh),
       fatigue_risk_score      = IF(fatigue_risk_score IS NULL,
                                    CASE injury_risk
                                      WHEN 'Low' THEN 0.00
                                      WHEN 'Medium' THEN 50.00
                                      WHEN 'High' THEN 100.00
                                      ELSE NULL END,
                                    fatigue_risk_score);

-- Backfill minutes_played / sprint_count from player_match_metrics when that table exists.
SET @has_pmm = (SELECT COUNT(*) FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_metrics');
SET @sql = IF(@has_pmm > 0,
  'UPDATE player_match_stats pms
      JOIN player_match_metrics mpm ON mpm.stat_id = pms.stat_id AND mpm.metric_key = ''minutes_played''
      SET pms.minutes_played = mpm.value
    WHERE pms.minutes_played IS NULL AND mpm.value IS NOT NULL',
  'SELECT ''no player_match_metrics for minutes backfill''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(@has_pmm > 0,
  'UPDATE player_match_stats pms
      JOIN player_match_metrics mpm ON mpm.stat_id = pms.stat_id AND mpm.metric_key = ''sprint_count''
      SET pms.sprint_count = ROUND(mpm.value)
    WHERE pms.sprint_count IS NULL AND mpm.value IS NOT NULL',
  'SELECT ''no player_match_metrics for sprint backfill''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
