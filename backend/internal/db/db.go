package db

import (
	"database/sql"
	"fmt"

	_ "github.com/go-sql-driver/mysql"
)

func Open(dsn string) (*sql.DB, error) {
	if dsn == "" {
		return nil, fmt.Errorf("DATABASE_DSN or DATABASE_URI is required")
	}
	conn, err := sql.Open("mysql", dsn)
	if err != nil {
		return nil, err
	}
	conn.SetMaxOpenConns(10)
	conn.SetMaxIdleConns(5)
	if err := conn.Ping(); err != nil {
		return nil, err
	}
	return conn, nil
}

func Migrate(conn *sql.DB) error {
	_, err := conn.Exec(schema)
	return err
}

const schema = `
CREATE TABLE IF NOT EXISTS v2_users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(100) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role VARCHAR(50) NOT NULL DEFAULT 'user',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS v2_sessions (
  token_hash CHAR(64) PRIMARY KEY,
  user_id INT NOT NULL,
  expires_at DATETIME NOT NULL,
  INDEX idx_v2_sessions_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS v2_stacks (
  id VARCHAR(36) PRIMARY KEY,
  name VARCHAR(63) NOT NULL UNIQUE,
  owner_id INT NOT NULL,
  source VARCHAR(16) NOT NULL,
  template_id VARCHAR(64) NULL,
  dir VARCHAR(512) NOT NULL,
  desired_state VARCHAR(16) NOT NULL DEFAULT 'stopped',
  description VARCHAR(255) NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_v2_stacks_owner (owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS v2_services (
  id INT AUTO_INCREMENT PRIMARY KEY,
  stack_id VARCHAR(36) NOT NULL,
  name VARCHAR(100) NOT NULL,
  http TINYINT(1) NOT NULL DEFAULT 0,
  internal_port INT NULL,
  host_port INT NULL,
  logs_enabled TINYINT(1) NOT NULL DEFAULT 1,
  shell TINYINT(1) NOT NULL DEFAULT 0,
  UNIQUE KEY uniq_v2_service (stack_id, name),
  INDEX idx_v2_services_stack (stack_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS v2_domains (
  id INT AUTO_INCREMENT PRIMARY KEY,
  stack_id VARCHAR(36) NOT NULL,
  service_name VARCHAR(100) NOT NULL,
  hostname VARCHAR(255) NOT NULL,
  upstream_port INT NOT NULL,
  tls TINYINT(1) NOT NULL DEFAULT 0,
  cloudflare TINYINT(1) NOT NULL DEFAULT 0,
  cf_record_id VARCHAR(64) NOT NULL DEFAULT '',
  UNIQUE KEY uniq_v2_domain_host (hostname),
  INDEX idx_v2_domains_stack (stack_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS v2_subusers (
  id INT AUTO_INCREMENT PRIMARY KEY,
  stack_id VARCHAR(36) NOT NULL,
  user_id INT NOT NULL,
  UNIQUE KEY uniq_v2_subuser (stack_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS v2_activity (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NULL,
  stack_name VARCHAR(63) NOT NULL DEFAULT '',
  action VARCHAR(64) NOT NULL,
  detail TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_v2_activity_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS v2_schedules (
  id INT AUTO_INCREMENT PRIMARY KEY,
  stack_id VARCHAR(36) NOT NULL,
  action VARCHAR(16) NOT NULL,
  cron VARCHAR(64) NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 1,
  INDEX idx_v2_schedules_stack (stack_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS v2_settings (
  id INT PRIMARY KEY,
  discord_webhook VARCHAR(512) NOT NULL DEFAULT '',
  cloudflare_token VARCHAR(512) NOT NULL DEFAULT '',
  public_ip VARCHAR(64) NOT NULL DEFAULT '',
  acme_email VARCHAR(255) NOT NULL DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS v2_template_overrides (
  id VARCHAR(64) PRIMARY KEY,
  yaml MEDIUMTEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
`
