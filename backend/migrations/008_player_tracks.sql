-- Migration 008: player tracks (POST /api/videos/{id}/tracks, GET/DELETE /api/tracks/{track_id}).
-- Run AFTER 001-007. Fresh installs don't need it (schema.sql has everything).
-- Usage (from backend/):  mysql -u root -p < migrations/008_player_tracks.sql
-- Idempotent: safe to run more than once (MySQL 8+ and MariaDB). Adds one table; changes and drops nothing.
--  * player_tracks: one "follow this player through the clip" track per row. Target = a box on one frame
--    (target_mode 'bbox', normalised [x, y, w, h]), an app player_id ('player') or a shirt number ('jersey', team
--    optional). Status/stage/progress like match_videos; files live in CV_OUTPUT_DIR/track_<track_id>/.

USE soccer_analytics_app;

-- FK columns get the same type as the key they reference: 'int' (schema.sql) or 'int unsigned' (original ERD).
SET @vid_type = (SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos' AND COLUMN_NAME = 'video_id');
SET @uid_type = (SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'user_id');
SET @pid_type = (SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'players' AND COLUMN_NAME = 'player_id');

SET @sql = CONCAT('CREATE TABLE IF NOT EXISTS player_tracks (
  track_id       INT          NOT NULL AUTO_INCREMENT,
  video_id       ', @vid_type, '          NOT NULL,
  user_id        ', @uid_type, '          NOT NULL,
  target_mode    VARCHAR(10)  NOT NULL,
  init_frame     INT          NULL,
  init_t         FLOAT        NULL,
  bbox_x         FLOAT        NULL,
  bbox_y         FLOAT        NULL,
  bbox_w         FLOAT        NULL,
  bbox_h         FLOAT        NULL,
  player_id      ', @pid_type, '          NULL,
  jersey_number  INT          NULL,
  team           VARCHAR(1)   NULL,
  fps            FLOAT        NULL,
  frame_count    INT          NULL,
  width          INT          NULL,
  height         INT          NULL,
  status         ENUM(''queued'',''processing'',''done'',''failed'') NOT NULL DEFAULT ''queued'',
  stage          VARCHAR(20)  NOT NULL DEFAULT ''queued'',
  progress       INT          NOT NULL DEFAULT 0,
  error_message  TEXT         NULL,
  output_dir     VARCHAR(500) NULL,
  frames_path    VARCHAR(500) NULL,
  annotated_path VARCHAR(500) NULL,
  meta           TEXT         NULL,
  stats          TEXT         NULL,
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SELECT 'migration 008_player_tracks applied' AS status;
