-- Migration 010: player fatigue / injury-risk model (v0.7.0) on soccer_analytics_app.
-- Adds csv_uploads, athlete_logs (heart rate AES-256-GCM encrypted) and player_match_risk (risk score + feature
-- snapshot AES-256-GCM encrypted). Run AFTER 001-009. Fresh installs don't need it (schema.sql has everything).
-- Usage (from backend/):  mysql -u root -p < migrations/010_player_risk.sql
--   or:  sed '/^USE /d' migrations/010_player_risk.sql | mysql -u root soccer_analytics_app
-- Idempotent. Adds three tables; changes and drops nothing. Then backfill: .venv/bin/python -m ml.backfill_risk

USE soccer_analytics_app;

-- FK columns get the same type as the key they reference ('int' in schema.sql, 'int unsigned' in the original ERD).
SET @uid_type = (SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'user_id');
SET @tid_type = (SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'teams' AND COLUMN_NAME = 'team_id');
SET @pid_type = (SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'players' AND COLUMN_NAME = 'player_id');
SET @mid_type = (SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'matches' AND COLUMN_NAME = 'match_id');
SET @vid_type = (SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_videos' AND COLUMN_NAME = 'video_id');
SET @sid_type = (SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'player_match_stats' AND COLUMN_NAME = 'stat_id');

SET @sql = CONCAT('CREATE TABLE IF NOT EXISTS csv_uploads (
  upload_id      INT          NOT NULL AUTO_INCREMENT,
  user_id        ', @uid_type, ' NOT NULL,
  team_id        ', @tid_type, ' NULL,
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = CONCAT('CREATE TABLE IF NOT EXISTS athlete_logs (
  log_id             INT     NOT NULL AUTO_INCREMENT,
  upload_id          INT     NOT NULL,
  player_id          ', @pid_type, ' NOT NULL,
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = CONCAT('CREATE TABLE IF NOT EXISTS player_match_risk (
  risk_id          INT          NOT NULL AUTO_INCREMENT,
  player_id        ', @pid_type, ' NOT NULL,
  source           VARCHAR(10)  NOT NULL,
  stat_id          ', @sid_type, ' NULL,
  log_id           INT          NULL,
  match_id         ', @mid_type, ' NULL,
  video_id         ', @vid_type, ' NULL,
  score_date       DATE         NULL,
  risk_percent_enc TEXT         NULL,
  level            VARCHAR(10)  NOT NULL DEFAULT ''unknown'',
  score_status     VARCHAR(20)  NOT NULL DEFAULT ''scored'',
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SELECT 'migration 010_player_risk applied' AS status;
