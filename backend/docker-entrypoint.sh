#!/bin/sh
# Container entrypoint: fix cache ownership, migrate, then run the command.
set -eu

# Host volumes (Railway, Render, Fly) are mounted owned by root, hiding the
# directory the image prepared. Take ownership once, then drop to `app`: the
# server itself never runs as root.
if [ "$(id -u)" = "0" ]; then
    mkdir -p "$FASTF1_CACHE_DIR"
    chown app:app "$FASTF1_CACHE_DIR"
    # setpriv keeps HOME=/root. libpq then fails on a *denied* read of
    # /root/.postgresql/postgresql.crt (a missing one is fine), so every
    # connection is refused. --reset-env would fix HOME but drop DATABASE_URL.
    export HOME=/home/app
    exec setpriv --reuid=app --regid=app --init-groups "$0" "$@"
fi

# One instance is assumed (see app/ingestion/runner.py), so migrating at boot
# cannot race another container. Set RUN_MIGRATIONS=false to migrate by hand.
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    alembic upgrade head
fi

exec "$@"
