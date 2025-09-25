#!/usr/bin/env bash
set -euo pipefail

# Non-Docker rollout script.
# Expects:
#   - /etc/geoinfer/.env to exist (populated by caller)
#   - Source code present under /opt/geoinfer/app
#   - Network access for installing uv/python if missing

WORKDIR="/root/app"
SERVICE_NAME="geoinfer-api"
ROLL_SCRIPT="/root/deploy/remote_rollout_nodocker.sh"
ROLL_MARKER="/root/rollout.pending"

echo "[remote:nodocker] Ensuring directories ..."
sudo mkdir -p "$WORKDIR"
sudo chown -R "$(whoami)":"$(whoami)" "$WORKDIR"

echo "[remote:nodocker] Installing nginx if missing ..."
if ! command -v nginx >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y nginx
fi

echo "[remote:nodocker] Marking rollout as pending ..."
date -Is > "$ROLL_MARKER"

echo "[remote:nodocker] Installing uv if missing ..."
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "[remote:nodocker] Ensuring Python toolchain for project ..."
export PATH="$HOME/.local/bin:$PATH"
# Let uv manage Python that satisfies pyproject requires-python
uv python install 3.12 >/dev/null 2>&1 || true

echo "[remote:nodocker] Syncing dependencies ..."
cd "$WORKDIR"

# Set temporary directory to use /root/tmp instead of /tmp to avoid disk space issues
export TMPDIR="/root/tmp"
mkdir -p "$TMPDIR"
echo "[remote:nodocker] Using temporary directory: $TMPDIR"

echo "[remote:nodocker] Installing remaining dependencies..."
uv sync --no-dev --no-cache

echo "[remote:nodocker] Running Alembic migrations ..."
PYTHONPATH=. uv run alembic -c src/database/alembic.ini upgrade head

echo "[remote:nodocker] Verifying Alembic migration state ..."
REV_OUTPUT=$(PYTHONPATH=. uv run alembic -c src/database/alembic.ini current || true)
HEAD_OUTPUT=$(PYTHONPATH=. uv run alembic -c src/database/alembic.ini heads || true)
if [ -z "$REV_OUTPUT" ] || [ -z "$HEAD_OUTPUT" ]; then
  echo "[remote:nodocker] Unable to determine Alembic revisions (current/heads)." >&2
  exit 1
fi

# Extract hex-like revision ids from outputs
CURRENT_ID=$(printf "%s" "$REV_OUTPUT" | grep -Eo '[0-9a-f]+' | head -n1 || true)
HEAD_ID=$(printf "%s" "$HEAD_OUTPUT" | grep -Eo '[0-9a-f]+' | head -n1 || true)

echo "[remote:nodocker] Current rev: ${CURRENT_ID:-unknown}; Head rev: ${HEAD_ID:-unknown}"
if [ -z "$CURRENT_ID" ] || [ -z "$HEAD_ID" ] || [ "$CURRENT_ID" != "$HEAD_ID" ]; then
  echo "[remote:nodocker] Migrations are not at head. Aborting restart." >&2
  exit 1
fi

echo "[remote:nodocker] Configuring nginx reverse proxy ..."
sudo cp /root/deploy/nginx.conf /etc/nginx/sites-available/geoinfer
sudo ln -sf /etc/nginx/sites-available/geoinfer /etc/nginx/sites-enabled/geoinfer
sudo rm -f /etc/nginx/sites-enabled/default  # Remove default nginx site
sudo nginx -t  # Test nginx configuration
sudo systemctl enable nginx
sudo systemctl restart nginx

echo "[remote:nodocker] Writing/refreshing systemd unit ..."
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
CURRENT_USER="$(whoami)"
sudo bash -c "cat > ${UNIT_FILE}" <<EOF
[Unit]
Description=GeoInfer API (uvicorn via uv)
After=network.target

[Service]
User=${CURRENT_USER}
WorkingDirectory=${WORKDIR}
EnvironmentFile=/etc/geoinfer/.env
Environment=PYTHONPATH=${WORKDIR}
ExecStart=/bin/bash -lc 'export PATH=\"$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin\"; uv run prod'
Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

echo "[remote:nodocker] Creating reboot-resume rollout unit ..."
RESUME_UNIT="/etc/systemd/system/geoinfer-rollout.service"
sudo bash -c "cat > ${RESUME_UNIT}" <<EOF
[Unit]
Description=GeoInfer Rollout Resume (run rollout if pending)
After=network-online.target
Wants=network-online.target

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

echo "[remote:nodocker] Reloading and starting service ..."
sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME} >/dev/null 2>&1 || true
sudo systemctl restart ${SERVICE_NAME}

echo "[remote:nodocker] Waiting for API health on :8010 ..."
for i in $(seq 1 60); do
  if curl -fsS http://localhost:8010/health >/dev/null 2>&1; then
    echo "[remote:nodocker] API service is healthy on port 8010."
    break
  fi
  echo "[remote:nodocker] [$i/60] API not healthy yet; retrying ..."
  sleep 2
  if [ $i -eq 60 ]; then
    echo "[remote:nodocker] API health check failed after restart." >&2
    sudo journalctl -u ${SERVICE_NAME} --no-pager -n 200 || true
    exit 1
  fi
done

echo "[remote:nodocker] Waiting for nginx proxy on :80 ..."
for i in $(seq 1 30); do
  if curl -fsS http://localhost/health >/dev/null 2>&1; then
    echo "[remote:nodocker] Nginx proxy is working. Service is fully healthy."
    rm -f "$ROLL_MARKER" || true
    exit 0
  fi
  echo "[remote:nodocker] [$i/30] Nginx proxy not ready yet; retrying ..."
  sleep 2
done

echo "[remote:nodocker] Nginx proxy health check failed." >&2
sudo nginx -t || true
sudo systemctl status nginx || true
exit 1


