#!/bin/sh
set -eu

DB_PATH="${1:-data/family_finance_bot.sqlite3}"
BACKUP_DIR="${2:-backups}"

if [ ! -f "$DB_PATH" ]; then
  echo "Database file not found: $DB_PATH" >&2
  exit 1
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "sqlite3 command is required for backups" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_PATH="$BACKUP_DIR/family_finance_bot_$TIMESTAMP.sqlite3"

sqlite3 "$DB_PATH" ".backup '$BACKUP_PATH'"
echo "$BACKUP_PATH"
