#!/usr/bin/env bash
# Build the images here, copy them and the deployment files to the server, then deploy.
# The server only loads images; it never builds them.
# Usage: demo/deploy/release.sh deploy@host [remote directory]   (default: out-of-frame)
set -euo pipefail

host="${1:?Usage: release.sh deploy@host [remote directory]}"
remote_dir="${2:-out-of-frame}"
cd "$(dirname "$0")/../.."

if [[ -n "$(git status --porcelain)" && "${OUT_OF_FRAME_ALLOW_DIRTY:-}" != 1 ]]; then
  echo "Commit or stash local changes first, or set OUT_OF_FRAME_ALLOW_DIRTY=1." >&2
  exit 1
fi

docker build --platform linux/amd64 -t out-of-frame-backend:local -f demo/Dockerfile .
docker build --platform linux/amd64 -t out-of-frame-web:local demo/frontend

# Deployment files only; demo/.env stays on the server.
tar -czf - demo/compose.yaml demo/Caddyfile demo/db/schema.sql demo/deploy/deploy.sh |
  ssh "$host" "mkdir -p '$remote_dir' && tar -xzf - -C '$remote_dir'"
docker save out-of-frame-backend:local out-of-frame-web:local | gzip -1 |
  ssh "$host" "gunzip | docker load"
ssh "$host" "'$remote_dir/demo/deploy/deploy.sh'"
