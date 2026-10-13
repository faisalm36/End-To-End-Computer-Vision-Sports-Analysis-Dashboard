-- Migration 005: user-scoped match tags + match results (score, our_side, W/D/L).
-- Run AFTER 004. Fresh installs don't need it (schema.sql has everything).
-- Usage (from backend/):  mysql -u root -p < migrations/005_tags_results.sql
-- Idempotent: safe to run more than once (MySQL 8+ and MariaDB).

USE soccer_analytics_app;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'matches' AND COLUMN_NAME = 'home_score') = 0,
  'ALTER TABLE matches ADD COLUMN home_score INT NULL AFTER tactical_formation',
  'SELECT ''home_score exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'matches' AND COLUMN_NAME = 'away_score') = 0,
  'ALTER TABLE matches ADD COLUMN away_score INT NULL AFTER home_score',
  'SELECT ''away_score exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'matches' AND COLUMN_NAME = 'our_side') = 0,
  'ALTER TABLE matches ADD COLUMN our_side ENUM(''home'',''away'') NULL AFTER away_score',
  'SELECT ''our_side exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'matches' AND COLUMN_NAME = 'result') = 0,
  'ALTER TABLE matches ADD COLUMN result ENUM(''W'',''D'',''L'') NULL AFTER our_side',
  'SELECT ''result exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- FK columns get the same type as the key they reference: 'int' (schema.sql) or 'int unsigned' (original ERD).
SET @uid_type = (SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'user_id');
SET @mid_type = (SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'matches' AND COLUMN_NAME = 'match_id');

SET @sql = CONCAT('CREATE TABLE IF NOT EXISTS tag_keys (
  tag_key_id  INT          NOT NULL AUTO_INCREMENT,
  user_id     ', @uid_type, '          NOT NULL,
  name        VARCHAR(50)  NOT NULL,
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (tag_key_id),
  UNIQUE KEY uq_tag_keys_user_name (user_id, name),
  KEY ix_tag_keys_user_id (user_id),
  CONSTRAINT fk_tag_keys_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS tag_values (
  tag_value_id  INT          NOT NULL AUTO_INCREMENT,
  tag_key_id    INT          NOT NULL,
  value         VARCHAR(100) NOT NULL,                  -- case-insensitive unique per key (collation)
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (tag_value_id),
  UNIQUE KEY uq_tag_values_key_value (tag_key_id, value),
  KEY ix_tag_values_tag_key_id (tag_key_id),
  CONSTRAINT fk_tag_values_key FOREIGN KEY (tag_key_id) REFERENCES tag_keys (tag_key_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET @sql = CONCAT('CREATE TABLE IF NOT EXISTS match_tags (
  match_id      ', @mid_type, '      NOT NULL,
  tag_value_id  INT      NOT NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (match_id, tag_value_id),
  KEY ix_match_tags_tag_value_id (tag_value_id),
  CONSTRAINT fk_match_tags_match FOREIGN KEY (match_id) REFERENCES matches (match_id) ON DELETE CASCADE,
  CONSTRAINT fk_match_tags_value FOREIGN KEY (tag_value_id) REFERENCES tag_values (tag_value_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Backfill: existing matches.weather_condition -> a 'Weather' tag for the owner of the home team (no-op on re-run).
INSERT IGNORE INTO tag_keys (user_id, name)
  SELECT DISTINCT t.user_id, 'Weather' FROM matches m JOIN teams t ON t.team_id = m.home_team_id
  WHERE m.weather_condition IS NOT NULL AND TRIM(m.weather_condition) <> '';
INSERT IGNORE INTO tag_values (tag_key_id, value)
  SELECT DISTINCT k.tag_key_id, TRIM(m.weather_condition) FROM matches m
  JOIN teams t ON t.team_id = m.home_team_id
  JOIN tag_keys k ON k.user_id = t.user_id AND k.name = 'Weather'
  WHERE m.weather_condition IS NOT NULL AND TRIM(m.weather_condition) <> '';
INSERT IGNORE INTO match_tags (match_id, tag_value_id)
  SELECT m.match_id, v.tag_value_id FROM matches m
  JOIN teams t ON t.team_id = m.home_team_id
  JOIN tag_keys k ON k.user_id = t.user_id AND k.name = 'Weather'
  -- explicit COLLATE: original-ERD tables use utf8mb4_0900_ai_ci, the tag tables utf8mb4_unicode_ci
  JOIN tag_values v ON v.tag_key_id = k.tag_key_id AND v.value = TRIM(m.weather_condition) COLLATE utf8mb4_unicode_ci
  WHERE m.weather_condition IS NOT NULL AND TRIM(m.weather_condition) <> '';

SELECT 'migration 005_tags_results applied' AS status;
