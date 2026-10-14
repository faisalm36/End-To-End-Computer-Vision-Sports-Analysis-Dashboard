-- Migration 003: video stage/progress for the UI + thumbnail path.
-- Run AFTER 001 and 002. Fresh installs don't need it (schema.sql already has these columns).
-- Usage (from backend/):  mysql -u root -p < migrations/003_video_progress_thumbnails.sql
-- Idempotent: safe to run more than once (MySQL 8+ and MariaDB).

USE soccer_analytics_app;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos' AND COLUMN_NAME = 'stage') = 0,
  'ALTER TABLE match_videos ADD COLUMN stage VARCHAR(20) NOT NULL DEFAULT ''queued'' AFTER processing_status',
  'SELECT ''stage exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos' AND COLUMN_NAME = 'progress') = 0,
  'ALTER TABLE match_videos ADD COLUMN progress INT NOT NULL DEFAULT 0 AFTER stage',
  'SELECT ''progress exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos' AND COLUMN_NAME = 'thumbnail_path') = 0,
  'ALTER TABLE match_videos ADD COLUMN thumbnail_path VARCHAR(500) NULL AFTER error_message',
  'SELECT ''thumbnail_path exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Backfill stage/progress from status for rows that predate this migration (no-op on re-run).
UPDATE match_videos SET stage = 'done',   progress = 100 WHERE processing_status = 'done'       AND stage = 'queued';
UPDATE match_videos SET stage = 'failed'                 WHERE processing_status = 'failed'     AND stage = 'queued';
UPDATE match_videos SET stage = 'detect', progress = 10  WHERE processing_status = 'processing' AND stage = 'queued';

SELECT 'migration 003_video_progress_thumbnails applied' AS status;
