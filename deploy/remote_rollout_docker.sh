#!/usr/bin/env bash
set -euo pipefail

# Docker-based rollout script.
# Expects:
#   - /etc/geoinfer/.env to exist (populated by caller)
#   - Source code present under /root/app
#   - Docker installed and running
#   - Network access for pulling/building images

WORKDIR="/root/app"
SERVICE_NAME="geoinfer-api"
CONTAINER_NAME="geoinfer-api-prod"
IMAGE_NAME="geoinfer-api:latest"
ROLL_SCRIPT="/root/deploy/remote_rollout_docker.sh"
ROLL_MARKER="/root/rollout.pending"

echo "[remote:docker] Ensuring directories ..."
sudo mkdir -p "$WORKDIR"
sudo chown -R "$(whoami)":"$(whoami)" "$WORKDIR"

echo "[remote:docker] Marking rollout as pending ..."
date -Is > "$ROLL_MARKER"

echo "[remote:docker] Installing Docker if missing ..."
if ! command -v docker >/dev/null 2>&1; then
  # Install Docker using official script
  curl -fsSL https://get.docker.com -o get-docker.sh
  sudo sh get-docker.sh
  sudo usermod -aG docker "$(whoami)"
  # Start Docker service
  sudo systemctl enable docker
  sudo systemctl start docker
  echo "[remote:docker] Docker installed. You may need to log out and back in for group changes to take effect."
fi

echo "[remote:docker] Verifying Docker is running ..."
if ! docker info >/dev/null 2>&1; then
  echo "[remote:docker] Starting Docker service ..."
  sudo systemctl start docker
  sleep 5
fi

echo "[remote:docker] Verifying project files are present ..."
cd "$WORKDIR"
echo "[remote:docker] Contents of $WORKDIR:"
ls -la .

if [ ! -f Dockerfile ]; then
  echo "[remote:docker] ERROR: Dockerfile not found in $WORKDIR" >&2
  exit 1
fi

if [ ! -f pyproject.toml ]; then
  echo "[remote:docker] ERROR: pyproject.toml not found in $WORKDIR" >&2
  exit 1
fi

echo "[remote:docker] ✓ Required files found"

echo "[remote:docker] Checking for existing containers and port conflicts ..."
if docker ps -a --format "table {{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
  echo "[remote:docker] Stopping and removing existing container ..."
  docker stop "$CONTAINER_NAME" || true
  docker rm "$CONTAINER_NAME" || true
else
  echo "[remote:docker] No existing container found"
fi

echo "[remote:docker] Forcefully clearing port 80 ..."

# Stop nginx unconditionally
echo "[remote:docker] Stopping nginx ..."
sudo systemctl stop nginx 2>/dev/null || true
sudo systemctl disable nginx 2>/dev/null || true

# Stop old geoinfer-api service unconditionally  
echo "[remote:docker] Stopping old geoinfer-api systemd service ..."
sudo systemctl stop geoinfer-api 2>/dev/null || true
sudo systemctl disable geoinfer-api 2>/dev/null || true

# Kill any processes using port 80
echo "[remote:docker] Killing processes on port 80 ..."
sudo fuser -k 80/tcp 2>/dev/null || true

# Wait and verify port is free
sleep 3
echo "[remote:docker] Checking if port 80 is now free ..."
if lsof -i :80 >/dev/null 2>&1; then
  echo "[remote:docker] WARNING: Port 80 still in use after cleanup:"
  lsof -i :80 || true
  echo "[remote:docker] Attempting more aggressive cleanup ..."
  
  # More aggressive kill
  sudo pkill -f nginx || true
  sudo pkill -f uvicorn || true
  sudo fuser -k -9 80/tcp 2>/dev/null || true
  sleep 2
  
  # Final check
  if lsof -i :80 >/dev/null 2>&1; then
    echo "[remote:docker] ERROR: Unable to free port 80. Manual intervention required." >&2
    lsof -i :80 || true
    exit 1
  fi
fi

echo "[remote:docker] ✓ Port 80 is now free"

echo "[remote:docker] Building production Docker image ..."
docker build -t "$IMAGE_NAME" --build-arg INSTALL_DEV=false .

echo "[remote:docker] Running database migrations in temporary container ..."
# Run migrations using a temporary container with proper PYTHONPATH
docker run --rm \
  --env-file /etc/geoinfer/.env \
  --network host \
  -e PYTHONPATH=/app \
  "$IMAGE_NAME" \
  uv run alembic -c src/database/alembic.ini upgrade head

echo "[remote:docker] Verifying Alembic migration state ..."
REV_OUTPUT=$(docker run --rm \
  --env-file /etc/geoinfer/.env \
  --network host \
  -e PYTHONPATH=/app \
  "$IMAGE_NAME" \
  uv run alembic -c src/database/alembic.ini current || true)

HEAD_OUTPUT=$(docker run --rm \
  --env-file /etc/geoinfer/.env \
  --network host \
  -e PYTHONPATH=/app \
  "$IMAGE_NAME" \
  uv run alembic -c src/database/alembic.ini heads || true)

if [ -z "$REV_OUTPUT" ] || [ -z "$HEAD_OUTPUT" ]; then
  echo "[remote:docker] Unable to determine Alembic revisions (current/heads)." >&2
  exit 1
fi

# Extract hex-like revision ids from outputs
CURRENT_ID=$(printf "%s" "$REV_OUTPUT" | grep -Eo '[0-9a-f]+' | head -n1 || true)
HEAD_ID=$(printf "%s" "$HEAD_OUTPUT" | grep -Eo '[0-9a-f]+' | head -n1 || true)

echo "[remote:docker] Current rev: ${CURRENT_ID:-unknown}; Head rev: ${HEAD_ID:-unknown}"
if [ -z "$CURRENT_ID" ] || [ -z "$HEAD_ID" ] || [ "$CURRENT_ID" != "$HEAD_ID" ]; then
  echo "[remote:docker] Migrations are not at head. Aborting deployment." >&2
  exit 1
fi

echo "[remote:docker] Creating Docker network if not exists ..."
docker network create geoinfer-net 2>/dev/null || true

echo "[remote:docker] Starting production container ..."
# Start the container in detached mode with restart policy
docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  --network geoinfer-net \
  --env-file /etc/geoinfer/.env \
  -v "$WORKDIR/logs":/app/logs \
  "$IMAGE_NAME"

echo "[remote:docker] Starting Caddy reverse proxy with HTTPS ..."
# Stop existing caddy if running
docker stop caddy-proxy 2>/dev/null || true
docker rm caddy-proxy 2>/dev/null || true

# Start Caddy with inline config for HTTPS termination
docker run -d \
  --name caddy-proxy \
  --restart unless-stopped \
  --network geoinfer-net \
  -p 80:80 \
  -p 443:443 \
  -v caddy_data:/data \
  -v caddy_config:/config \
  caddy:alpine \
  caddy reverse-proxy --from :80 --to geoinfer-api-prod:8010

echo "[remote:docker] Waiting for API health on container port 8010 (external port 80) ..."
for i in $(seq 1 60); do
  if curl -fsS http://localhost:80/health >/dev/null 2>&1; then
    echo "[remote:docker] API service is healthy on port 80."
    break
  fi
  echo "[remote:docker] [$i/60] API not healthy yet; retrying ..."
  sleep 2
  if [ $i -eq 60 ]; then
    echo "[remote:docker] API health check failed after deployment." >&2
    echo "[remote:docker] Container logs:" >&2
    docker logs "$CONTAINER_NAME" --tail 50 || true
    exit 1
  fi
done

echo "[remote:docker] Writing systemd unit for container management ..."
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}-docker.service"
CURRENT_USER="$(whoami)"
sudo bash -c "cat > ${UNIT_FILE}" <<EOF
[Unit]
Description=GeoInfer API Docker Container
Requires=docker.service
After=docker.service
StartLimitIntervalSec=0

[Service]
Type=oneshot
RemainAfterExit=yes
User=${CURRENT_USER}
WorkingDirectory=${WORKDIR}
ExecStart=/bin/bash -c 'docker start ${CONTAINER_NAME} || docker run -d --name ${CONTAINER_NAME} --restart unless-stopped -p 80:8010 --env-file /etc/geoinfer/.env -v ${WORKDIR}/logs:/app/logs ${IMAGE_NAME}'
ExecStop=/bin/bash -c 'docker stop ${CONTAINER_NAME}'
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

echo "[remote:docker] Creating reboot-resume rollout unit ..."
RESUME_UNIT="/etc/systemd/system/geoinfer-rollout.service"
sudo bash -c "cat > ${RESUME_UNIT}" <<EOF
[Unit]
Description=GeoInfer Rollout Resume (run rollout if pending)
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
User=${CURRENT_USER}
WorkingDirectory=/root
EnvironmentFile=/etc/geoinfer/.env
ExecStart=/bin/bash -lc '[ -f ${ROLL_MARKER} ] && bash ${ROLL_SCRIPT} || true'
RemainAfterExit=no

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable geoinfer-rollout.service >/dev/null 2>&1 || true
sudo systemctl enable ${SERVICE_NAME}-docker.service >/dev/null 2>&1 || true

echo "[remote:docker] Final health check ..."
if curl -fsS http://localhost:80/health >/dev/null 2>&1; then
  echo "[remote:docker] ✅ Deployment successful! API is healthy on port 80."
  rm -f "$ROLL_MARKER" || true
  
  echo "[remote:docker] Container status:"
  docker ps --filter "name=${CONTAINER_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
  
  exit 0
else
  echo "[remote:docker] ❌ Final health check failed." >&2
  docker logs "$CONTAINER_NAME" --tail 20 || true
  exit 1
fi
