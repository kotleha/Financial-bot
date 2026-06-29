#!/bin/sh
set -eu

if [ -f /run/secrets/bot_token ] && [ -z "${BOT_TOKEN:-}" ]; then
  export BOT_TOKEN="$(cat /run/secrets/bot_token)"
fi

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  alembic upgrade head
fi

if [ "${RUN_SEED:-1}" = "1" ]; then
  python scripts/seed_initial_data.py --env-file ""
fi

exec "$@"
