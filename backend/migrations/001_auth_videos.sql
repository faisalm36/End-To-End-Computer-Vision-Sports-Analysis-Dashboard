-- Migration 001: auth + user video uploads.
-- For a database created from the ORIGINAL schema.sql (step 2). Fresh installs don't need this:
-- the current schema.sql already contains these changes.
-- Usage (from backend/):  mysql -u root -p < migrations/001_auth_videos.sql
-- Idempotent: safe to run more than once (works on MySQL 8+ and MariaDB).
-- Original-ERD databases (INT UNSIGNED keys): run 000_legacy_erd_compat.sql first. Foreign-key columns are created
-- with the SAME type as the key they reference (INT or INT UNSIGNED), and a user_id column left behind by an
-- earlier failed run (signed INT, no FK) is converted before the FK is added.

USE soccer_analytics_app;

-- helper pattern: run an ALTER only if the column / index / FK doesn't exist yet
-- ---------------------------------------------------------------- match_videos.user_id
-- type of the referenced key: 'int' (schema.sql) or 'int unsigned' (original ERD)
SET @uid_type = (SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'user_id');
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos' AND COLUMN_NAME = 'user_id') = 0,
  CONCAT('ALTER TABLE match_videos ADD COLUMN user_id ', @uid_type, ' NULL AFTER match_id, ADD KEY ix_match_videos_user_id (user_id)'),
  'SELECT ''user_id exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- resume a failed earlier run: the column exists with the wrong signedness and no FK yet -> match users.user_id
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos' AND COLUMN_NAME = 'user_id'
                 AND COLUMN_TYPE <> @uid_type) > 0
              AND (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos'
                     AND CONSTRAINT_NAME = 'fk_match_videos_user') = 0,
  CONCAT('ALTER TABLE match_videos MODIFY COLUMN user_id ', @uid_type, ' NULL'),
  'SELECT ''user_id type ok''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos'
                 AND CONSTRAINT_NAME = 'fk_match_videos_user') = 0,
  'ALTER TABLE match_videos ADD CONSTRAINT fk_match_videos_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE',
  'SELECT ''fk_match_videos_user exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------- match_videos.title
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos' AND COLUMN_NAME = 'title') = 0,
  'ALTER TABLE match_videos ADD COLUMN title VARCHAR(255) NULL AFTER user_id',
  'SELECT ''title exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------- match_videos.error_message
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos' AND COLUMN_NAME = 'error_message') = 0,
  'ALTER TABLE match_videos ADD COLUMN error_message TEXT NULL AFTER processing_status',
  'SELECT ''error_message exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------- match_videos.processed_at
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos' AND COLUMN_NAME = 'processed_at') = 0,
  'ALTER TABLE match_videos ADD COLUMN processed_at DATETIME NULL AFTER uploaded_at',
  'SELECT ''processed_at exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------- processing_status enum
-- pending/processing/completed/failed  ->  queued/processing/done/failed
-- 1) widen to the union (NULLable, so legacy NULL rows survive), 2) remap old values, 3) narrow to the new set.
-- Works whatever subset the column started with (step 2: pending/..., original ERD: queued/processing/completed/failed).
ALTER TABLE match_videos MODIFY COLUMN processing_status
  ENUM('pending','processing','completed','failed','queued','done') NULL DEFAULT 'queued';
UPDATE match_videos SET processing_status = 'queued' WHERE processing_status = 'pending' OR processing_status IS NULL;
UPDATE match_videos SET processing_status = 'done'   WHERE processing_status = 'completed';
ALTER TABLE match_videos MODIFY COLUMN processing_status
  ENUM('queued','processing','done','failed') NOT NULL DEFAULT 'queued';

-- Backfill owner/title for pre-existing videos: owner = user who owns the match's home team.
UPDATE match_videos v
  JOIN matches m ON m.match_id = v.match_id
  JOIN teams t   ON t.team_id  = m.home_team_id
SET v.user_id = t.user_id
WHERE v.user_id IS NULL;
UPDATE match_videos SET title = file_name WHERE title IS NULL;

-- ---------------------------------------------------------------- tracking_detections extras
-- object_class: 'player' | 'ball' (CV output "class"); jersey_number: OCR result per detection
SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tracking_detections' AND COLUMN_NAME = 'object_class') = 0,
  'ALTER TABLE tracking_detections ADD COLUMN object_class VARCHAR(20) NOT NULL DEFAULT ''player'' AFTER frame_number',
  'SELECT ''object_class exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tracking_detections' AND COLUMN_NAME = 'jersey_number') = 0,
  'ALTER TABLE tracking_detections ADD COLUMN jersey_number INT NULL AFTER object_class',
  'SELECT ''jersey_number exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SELECT 'migration 001_auth_videos applied' AS status;
