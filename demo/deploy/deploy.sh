#!/usr/bin/env bash
# Start the demo with the loaded images. Run on the server as the deploy user;
# release.sh copies the images and this script and then runs it.
set -euo pipefail

cd "$(dirname "$0")/.."
env_file="${OUT_OF_FRAME_DEMO_ENV_FILE:-.env}"
if [[ ! -f "$env_file" ]]; then
  echo "Create demo/.env from demo/.env.example first." >&2
  exit 1
fi
compose=(docker compose --env-file "$env_file")

"${compose[@]}" up -d --no-build --wait postgres redis
# Schema changes need a stopped backend. The examples stay available meanwhile.
"${compose[@]}" stop backend
"${compose[@]}" run --rm --no-deps backend aegra db upgrade
"${compose[@]}" exec -T postgres \
  psql -U out_of_frame -d out_of_frame --set ON_ERROR_STOP=1 --single-transaction <db/schema.sql
"${compose[@]}" up -d --no-build --wait
docker image prune -f
"${compose[@]}" ps
