#!/usr/bin/env bash
set -euo pipefail

# Expects /etc/geoinfer/.env to exist, and IMAGE/DOCR_* envs exported by the caller.

echo "[remote] Pulling image: $IMAGE"
docker pull "$IMAGE"

echo "[remote] Capturing current container image for rollback ..."
OLD_IMAGE_ID=$(docker inspect --format='{{.Image}}' geoinfer-api 2>/dev/null || true)

echo "[remote] Running Alembic migrations via one-off container ..."
docker run --rm \
  --name geoinfer-api-migrate \
  --env-file /etc/geoinfer/.env \
  "$IMAGE" \
  uv run alembic -c src/database/alembic.ini upgrade head

echo "[remote] Starting canary on 8080 ..."
docker rm -f geoinfer-api-canary 2>/dev/null || true
docker run -d \
  --name geoinfer-api-canary \
  --restart unless-stopped \
  -p 8080:8010 \
  --env-file /etc/geoinfer/.env \
  "$IMAGE"

echo "[remote] Waiting for canary /health ..."
for i in $(seq 1 60); do
  if curl -fsS http://localhost:8080/health >/dev/null 2>&1; then
    echo "[remote] Canary is healthy."
    break
  fi
  echo "[remote] [$i/60] Canary not ready; retrying ..."
  sleep 2
  if [ "$i" = "60" ]; then
    echo "[remote] Canary failed to become healthy." >&2
    docker logs --tail=200 geoinfer-api-canary || true
    docker rm -f geoinfer-api-canary || true
    exit 1
  fi
done

echo "[remote] Swapping traffic to new version on port 80 ..."
docker rm -f geoinfer-api 2>/dev/null || true
if ! docker run -d \
  --name geoinfer-api \
  --restart unless-stopped \
  -p 80:8010 \
  --env-file /etc/geoinfer/.env \
  "$IMAGE"; then
  echo "[remote] New container failed to start; attempting rollback ..." >&2
  if [ -n "$OLD_IMAGE_ID" ]; then
    docker run -d \
      --name geoinfer-api \
      --restart unless-stopped \
      -p 80:8010 \
      --env-file /etc/geoinfer/.env \
      "$OLD_IMAGE_ID" || true
  fi
  exit 1
fi

echo "[remote] Cleaning up canary ..."
docker rm -f geoinfer-api-canary || true

echo "[remote] Verifying production health on port 80 ..."
for i in $(seq 1 60); do
  if curl -fsS http://localhost/health >/dev/null 2>&1; then
    echo "[remote] Deployment successful and healthy."
    exit 0
  fi
  echo "[remote] [$i/60] Waiting for production health ..."
  sleep 2
done

echo "[remote] Production health check failed after rollout." >&2
exit 1


