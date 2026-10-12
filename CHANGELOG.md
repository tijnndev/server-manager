# Changelog

All notable changes to server-manager are documented here. The format is
loosely based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

- Initial open-source release of the Go/React panel (the "remake").
  - Stack management from templates or custom compose files
  - Live status, logs, per-service shell over WebSocket
  - File browser/editor, git clone/pull
  - Domain publishing via host nginx + Let's Encrypt + Cloudflare
  - Cron schedules, sub-users, activity log
  - Mail account management (docker-mailserver + Roundcube)
  - Discord notifications
  - Legacy Python-panel migration tooling (`deploy/`)