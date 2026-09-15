#!/bin/sh
set -eu

/usr/local/bin/docker-entrypoint.sh "$@" &
child="$!"
trap 'kill -TERM "$child" 2>/dev/null || true' INT TERM

attempt=0
while :; do
  if ! kill -0 "$child" 2>/dev/null; then wait "$child"; exit $?; fi
  if pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
    if psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
      "SELECT to_regclass('research_db.reference_datasets') IS NOT NULL AND to_regclass('farm_db.sensor_readings') IS NOT NULL AND coalesce((SELECT count(*)>=4 FROM user_db.users WHERE status='active'),false)" \
      2>/dev/null | grep -q t; then
      echo "[NextFarm V9] Fresh standalone PostgreSQL schema is ready."
      break
    fi
  fi
  attempt=$((attempt+1))
  if [ "$attempt" -ge 180 ]; then
    echo "[NextFarm V9] Database/schema did not become ready." >&2
    kill -TERM "$child" 2>/dev/null || true
    wait "$child" || true
    exit 1
  fi
  sleep 1
done
wait "$child"
