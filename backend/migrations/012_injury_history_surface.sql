-- Migration 012 (v0.9.0): roster injury-risk model rir-1.0.
--   matches.surface, players.birth_date, player_injuries, player_risk_snapshots.
-- Idempotent: safe to run twice. FK column types copied from the live parent tables (like 010).
-- Run:  mysql -u root -p soccer_analytics_app < backend/migrations/012_injury_history_surface.sql

SET @has = (SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'matches' AND COLUMN_NAME = 'surface');
SET @sql = IF(@has = 0,
  'ALTER TABLE matches ADD COLUMN surface ENUM(''grass'',''turf'',''hybrid'',''indoor'',''unknown'') NOT NULL DEFAULT ''unknown''',
  'SELECT ''matches.surface exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has = (SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'players' AND COLUMN_NAME = 'birth_date');
SET @sql = IF(@has = 0, 'ALTER TABLE players ADD COLUMN birth_date DATE NULL', 'SELECT ''players.birth_date exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @uid_type = (SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'user_id');
SET @pid_type = (SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'players' AND COLUMN_NAME = 'player_id');
SET @mid_type = (SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'matches' AND COLUMN_NAME = 'match_id');

SET @sql = CONCAT('CREATE TABLE IF NOT EXISTS player_injuries (
  injury_id     INT NOT NULL AUTO_INCREMENT,
  player_id     ', @pid_type, ' NOT NULL,
  user_id       ', @uid_type, ' NOT NULL,
  body_part     ENUM(''hamstring'',''groin'',''quadriceps'',''calf'',''ankle'',''knee'',''foot'',''hip'',''back'',''shoulder'',''head'',''other'') NOT NULL,
  injury_type   ENUM(''muscle_strain'',''ligament_sprain'',''tendon'',''fracture'',''contusion'',''concussion'',''overuse'',''other'') NOT NULL,
  side          ENUM(''left'',''right'',''both'',''na'') NOT NULL DEFAULT ''na'',
  injury_date   DATE NOT NULL,
  return_date   DATE NULL,
  days_missed   INT NULL,
  is_recurrence TINYINT(1) NOT NULL DEFAULT 0,
  source        ENUM(''player'',''staff'',''system'') NOT NULL DEFAULT ''player'',
  notes_enc     TEXT NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (injury_id),
  KEY ix_pi_player_date (player_id, injury_date),
  KEY ix_pi_user (user_id),
  CONSTRAINT fk_pi_player FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE,
  CONSTRAINT fk_pi_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = CONCAT('CREATE TABLE IF NOT EXISTS player_risk_snapshots (
  snapshot_id   INT NOT NULL AUTO_INCREMENT,
  player_id     ', @pid_type, ' NOT NULL,
  match_id      ', @mid_type, ' NULL,
  kind          ENUM(''current'',''history'',''projection'') NOT NULL,
  as_of         DATE NOT NULL,
  next_surface  VARCHAR(10) NULL,
  score_enc     TEXT NOT NULL,
  band          VARCHAR(10) NOT NULL,
  confidence    VARCHAR(8) NOT NULL,
  factors_enc   TEXT NOT NULL,
  model_version VARCHAR(20) NOT NULL,
  computed_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (snapshot_id),
  UNIQUE KEY uq_prs (player_id, kind, as_of, match_id),
  KEY ix_prs_match (match_id),
  CONSTRAINT fk_prs_player FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE,
  CONSTRAINT fk_prs_match FOREIGN KEY (match_id) REFERENCES matches (match_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SELECT 'migration 012_injury_history_surface applied' AS status;
