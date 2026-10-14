-- Migration 000: compatibility for a database built from the ORIGINAL capstone ERD
-- (INT UNSIGNED keys, players.position ENUM('GK','DF','MF','FW') NOT NULL, player_match_stats with
--  distance_covered_meters / top_speed_kmh / fatigue_risk_score, tracking_detections with
--  x_center / y_center / bbox_width / bbox_height).
-- Run it FIRST, then 001 -> 006. On a step-2 schema.sql database or a fresh schema.sql install every step is a
-- no-op (each change is guarded by an information_schema check), so it is always safe to run.
-- Nothing is dropped: the legacy columns stay; they are only made NULLable where the app never writes them.
-- Usage (from backend/):  mysql -u root -p soccer_analytics_db < migrations/000_legacy_erd_compat.sql
-- Idempotent: safe to run more than once (MySQL 8.0+/26.x and MariaDB 10.5+).

USE soccer_analytics_app;

-- ---------------------------------------------------------------- players.position
-- The app stores free text (and the pipeline creates placeholder players with position 'Unassigned').
-- ENUM -> VARCHAR(30) NULL keeps the existing values ('GK','DF','MF','FW') as text.
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'players' AND COLUMN_NAME = 'position'
                 AND (DATA_TYPE <> 'varchar' OR IS_NULLABLE = 'NO')) > 0,
  'ALTER TABLE players MODIFY COLUMN position VARCHAR(30) NULL',
  'SELECT ''players.position ok''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------- player_match_stats: app columns
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_stats' AND COLUMN_NAME = 'top_speed_mph') = 0,
  'ALTER TABLE player_match_stats ADD COLUMN top_speed_mph DECIMAL(5,2) NULL',
  'SELECT ''top_speed_mph exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_stats' AND COLUMN_NAME = 'distance_km') = 0,
  'ALTER TABLE player_match_stats ADD COLUMN distance_km DECIMAL(6,3) NULL AFTER top_speed_mph',
  'SELECT ''distance_km exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_stats' AND COLUMN_NAME = 'injury_risk') = 0,
  'ALTER TABLE player_match_stats ADD COLUMN injury_risk ENUM(''Low'',''Medium'',''High'') NOT NULL DEFAULT ''Low'' AFTER distance_km',
  'SELECT ''injury_risk exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Backfill the new columns from the legacy ones (km/h -> mph, metres -> km). Only fills NULLs, so re-runs are no-ops.
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_stats'
                 AND COLUMN_NAME IN ('top_speed_kmh','distance_covered_meters')) = 2,
  'UPDATE player_match_stats
      SET top_speed_mph = IF(top_speed_mph IS NULL AND top_speed_kmh > 0, ROUND(top_speed_kmh / 1.609344, 2), top_speed_mph),
          distance_km   = IF(distance_km IS NULL AND distance_covered_meters > 0, ROUND(distance_covered_meters / 1000, 3), distance_km)',
  'SELECT ''no legacy speed/distance columns''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------- tracking_detections: corner bbox columns
-- Add bbox_x1..y2 NULL, backfill from the legacy centre/size columns, then make them NOT NULL like schema.sql.
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tracking_detections' AND COLUMN_NAME = 'bbox_x1') = 0,
  'ALTER TABLE tracking_detections ADD COLUMN bbox_x1 FLOAT NULL, ADD COLUMN bbox_y1 FLOAT NULL,
                                   ADD COLUMN bbox_x2 FLOAT NULL, ADD COLUMN bbox_y2 FLOAT NULL',
  'SELECT ''bbox_x1..y2 exist''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @legacy_bbox = (SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tracking_detections'
                      AND COLUMN_NAME IN ('x_center','y_center','bbox_width','bbox_height'));
SET @sql = IF(@legacy_bbox = 4,
  'UPDATE tracking_detections
      SET bbox_x1 = x_center - bbox_width / 2,  bbox_y1 = y_center - bbox_height / 2,
          bbox_x2 = x_center + bbox_width / 2,  bbox_y2 = y_center + bbox_height / 2
    WHERE bbox_x1 IS NULL',
  'SELECT ''no legacy bbox columns''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tracking_detections'
                 AND COLUMN_NAME IN ('bbox_x1','bbox_y1','bbox_x2','bbox_y2') AND IS_NULLABLE = 'YES') > 0,
  'ALTER TABLE tracking_detections MODIFY COLUMN bbox_x1 FLOAT NOT NULL, MODIFY COLUMN bbox_y1 FLOAT NOT NULL,
                                   MODIFY COLUMN bbox_x2 FLOAT NOT NULL, MODIFY COLUMN bbox_y2 FLOAT NOT NULL',
  'SELECT ''bbox_x1..y2 NOT NULL''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- The app never writes the legacy centre/size columns, so they must accept NULL (they're NOT NULL without a default).
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tracking_detections'
                 AND COLUMN_NAME IN ('x_center','y_center','bbox_width','bbox_height') AND IS_NULLABLE = 'NO') = 4,
  'ALTER TABLE tracking_detections MODIFY COLUMN x_center DECIMAL(7,2) NULL, MODIFY COLUMN y_center DECIMAL(7,2) NULL,
                                   MODIFY COLUMN bbox_width DECIMAL(6,2) NULL, MODIFY COLUMN bbox_height DECIMAL(6,2) NULL',
  'SELECT ''legacy bbox columns nullable or absent''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Ball detections use negative track ids (track_id < 0), so track_id must be signed.
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tracking_detections' AND COLUMN_NAME = 'track_id'
                 AND COLUMN_TYPE LIKE '%unsigned%') > 0,
  'ALTER TABLE tracking_detections MODIFY COLUMN track_id INT NOT NULL',
  'SELECT ''track_id signed''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------- match_videos.fps / users.email
-- fps is NULL until the CV pipeline reports it (the app may write NULL); keep the legacy default.
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos' AND COLUMN_NAME = 'fps'
                 AND IS_NULLABLE = 'NO') > 0,
  'ALTER TABLE match_videos MODIFY COLUMN fps FLOAT NULL DEFAULT 30',
  'SELECT ''fps nullable''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- the API accepts any valid e-mail (schema.sql: VARCHAR(255)); widening keeps the existing unique key.
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'email'
                 AND CHARACTER_MAXIMUM_LENGTH < 255) > 0,
  'ALTER TABLE users MODIFY COLUMN email VARCHAR(255) NOT NULL',
  'SELECT ''users.email length ok''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Legacy confidence DECIMAL(4,3) and pitch_x/pitch_y DECIMAL(6,2) hold the app's values; left as is.

SELECT 'migration 000_legacy_erd_compat applied' AS status;
