-- Migration 002: player stats stored per processed video + pipeline metadata.
-- Run AFTER 001_auth_videos.sql on a database created with the step-2 schema.sql.
-- Fresh installs don't need it: the current schema.sql already contains these changes.
-- Usage (from backend/):  mysql -u root -p < migrations/002_stats_per_video.sql
-- Idempotent: safe to run more than once (MySQL 8+ and MariaDB).
-- Original-ERD databases: run 000_legacy_erd_compat.sql first (it adds top_speed_mph / distance_km / injury_risk).

USE soccer_analytics_app;

-- ---------------------------------------------------------------- player_match_stats.video_id
-- same type as match_videos.video_id ('int' from schema.sql, 'int unsigned' in the original ERD)
SET @vid_type = (SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos' AND COLUMN_NAME = 'video_id');
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_stats' AND COLUMN_NAME = 'video_id') = 0,
  CONCAT('ALTER TABLE player_match_stats ADD COLUMN video_id ', @vid_type, ' NULL AFTER match_id, ADD KEY ix_player_match_stats_video_id (video_id)'),
  'SELECT ''video_id exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- resume a failed earlier run: the column exists with the wrong signedness and no FK yet
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_stats' AND COLUMN_NAME = 'video_id'
                 AND COLUMN_TYPE <> @vid_type) > 0
              AND (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_stats'
                     AND CONSTRAINT_NAME = 'fk_stats_video') = 0,
  CONCAT('ALTER TABLE player_match_stats MODIFY COLUMN video_id ', @vid_type, ' NULL'),
  'SELECT ''video_id type ok''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_stats'
                 AND CONSTRAINT_NAME = 'fk_stats_video') = 0,
  'ALTER TABLE player_match_stats ADD CONSTRAINT fk_stats_video FOREIGN KEY (video_id) REFERENCES match_videos (video_id) ON DELETE CASCADE',
  'SELECT ''fk_stats_video exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------- unique key: (player, match) -> (player, video)
SET @sql = IF((SELECT COUNT(*) FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_stats'
                 AND INDEX_NAME = 'uq_stats_player_video') = 0,
  'ALTER TABLE player_match_stats ADD UNIQUE KEY uq_stats_player_video (player_id, video_id)',
  'SELECT ''uq_stats_player_video exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- The old per-match unique key may be the only index starting with match_id (it backs fk_stats_match in the
-- original ERD), so make sure a plain match_id index exists before dropping it.
SET @sql = IF((SELECT COUNT(*) FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_stats' AND COLUMN_NAME = 'match_id'
                 AND SEQ_IN_INDEX = 1 AND NON_UNIQUE = 1) = 0,
  'ALTER TABLE player_match_stats ADD KEY ix_player_match_stats_match_id (match_id)',
  'SELECT ''match_id index exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- (ix_player_match_stats_player_id / fk_stats_player's index still backs fk_stats_player, so the old unique key can go)
-- step-2 name: uq_stats_player_match; original-ERD name: uq_player_match
SET @sql = IF((SELECT COUNT(*) FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_stats'
                 AND INDEX_NAME = 'uq_stats_player_match') > 0,
  'ALTER TABLE player_match_stats DROP INDEX uq_stats_player_match',
  'SELECT ''uq_stats_player_match already dropped''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_stats'
                 AND INDEX_NAME = 'uq_player_match') > 0,
  'ALTER TABLE player_match_stats DROP INDEX uq_player_match',
  'SELECT ''uq_player_match absent''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- speed/distance are NULL when the CV run had no calibration (already nullable; re-assert)
ALTER TABLE player_match_stats
  MODIFY COLUMN top_speed_mph DECIMAL(5,2) NULL,
  MODIFY COLUMN distance_km   DECIMAL(6,3) NULL;

-- ---------------------------------------------------------------- match_videos.pipeline_meta
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos' AND COLUMN_NAME = 'pipeline_meta') = 0,
  'ALTER TABLE match_videos ADD COLUMN pipeline_meta TEXT NULL AFTER error_message',
  'SELECT ''pipeline_meta exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Existing rows keep video_id = NULL (legacy stats, still counted by /api/players/stats).
SELECT 'migration 002_stats_per_video applied' AS status;
