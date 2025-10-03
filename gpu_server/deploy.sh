#!/bin/bash
# Deployment script for GPU server (runs directly on Vast.ai, no Docker)
# Usage: ./deploy.sh <user@host> <port> <ssh-key-path> [app_username] [app_password]

set -e

if [ "$#" -lt 3 ]; then
    echo "Usage: $0 <user@host> <port> <ssh-key-path> [app_username] [app_password]"
    echo "Example: $0 root@192.165.134.28 11233 ~/.ssh/id_vast admin mypassword"
    exit 1
fi

USER_HOST=$1
PORT=$2
SSH_KEY=$3
APP_USERNAME=${4:-admin}
APP_PASSWORD=${5:-changeme}

echo "🚀 Deploying GPU server to $USER_HOST:$PORT"

# Extract user and host
IFS='@' read -ra ADDR <<< "$USER_HOST"
USER="${ADDR[0]}"
HOST="${ADDR[1]}"

# Create remote directory
echo "📁 Creating remote directory..."
ssh -i "$SSH_KEY" -p "$PORT" "$USER_HOST" "mkdir -p ~/geoclip-gpu"

# Sync files
echo "📦 Syncing files..."
rsync -avz --delete -e "ssh -i $SSH_KEY -p $PORT" \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '.venv' \
    --exclude 'venv' \
    --exclude '*.pyc' \
    --exclude '.env' \
    --exclude '.idea' \
    --exclude '*.md' \
    --exclude 'deploy.sh' \
    --exclude 'Dockerfile' \
    --exclude '.dockerignore' \
    ./ \
    "$USER_HOST:~/geoclip-gpu/"

# No need to sync src/ - standalone GPU server

# Install dependencies and run server
echo "🐍 Installing dependencies and starting server..."
ssh -i "$SSH_KEY" -p "$PORT" "$USER_HOST" bash << EOF
set -e
cd ~/geoclip-gpu

# Install pip if needed
python3 -m pip --version || curl -sS https://bootstrap.pypa.io/get-pip.py | python3

# Install dependencies
echo "📦 Installing Python dependencies..."
python3 -m pip install --quiet --upgrade pip

# Install PyTorch with CUDA support first
echo "🔥 Installing PyTorch with CUDA..."
python3 -m pip install --quiet torch torchvision --index-url https://download.pytorch.org/whl/cu121

# Install other dependencies (using compatible versions)
echo "📦 Installing other dependencies..."
python3 -m pip install --quiet \
    fastapi \
    "uvicorn[standard]" \
    pydantic \
    python-multipart \
    python-dotenv \
    geoclip \
    pillow \
    pillow-heif \
    numpy \
    reverse_geocoder \
    aiohttp \
    supervisor

# Create .env file
cat > .env << ENVFILE
APP_USERNAME=$APP_USERNAME
APP_PASSWORD=$APP_PASSWORD
HOST=0.0.0.0
PORT=8000
ENVFILE

# Create supervisor config for 24/7 auto-restart
echo "⚙️  Setting up supervisor for auto-restart..."
mkdir -p /etc/supervisor/conf.d
cat > /etc/supervisor/conf.d/geoclip.conf << SUPERVISORCONF
[program:geoclip]
command=python3 -m uvicorn app:app --host 0.0.0.0 --port 8000
directory=/root/geoclip-gpu
autostart=true
autorestart=true
startretries=10
stderr_logfile=/root/geoclip-error.log
stdout_logfile=/root/geoclip.log
user=root
environment=PATH="/usr/local/bin:/usr/bin:/bin"
SUPERVISORCONF

# Start supervisord if not running
if ! pgrep supervisord > /dev/null; then
    echo "🚀 Starting supervisord..."
    supervisord -c /etc/supervisor/supervisord.conf || \
    (echo "[unix_http_server]
file=/var/run/supervisor.sock

[supervisord]
logfile=/var/log/supervisord.log
logfile_maxbytes=50MB
logfile_backups=10
loglevel=info
pidfile=/var/run/supervisord.pid
nodaemon=false

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix:///var/run/supervisor.sock

[include]
files = /etc/supervisor/conf.d/*.conf" > /etc/supervisor/supervisord.conf && \
    supervisord -c /etc/supervisor/supervisord.conf)
    sleep 2
fi

# Restart the geoclip service
echo "🔄 Restarting geoclip service..."
supervisorctl reread
supervisorctl update
supervisorctl restart geoclip

# Wait for server to start
sleep 5

# Check if server is running
if supervisorctl status geoclip | grep RUNNING > /dev/null; then
    echo "✅ Server started successfully with auto-restart enabled"
    supervisorctl status geoclip
else
    echo "❌ Server failed to start. Check logs:"
    tail -50 ~/geoclip.log
    tail -50 ~/geoclip-error.log
    exit 1
fi
EOF

echo ""
echo "✅ Deployment complete!"
echo "🌐 Server running at http://$HOST:8000"
echo "🔐 Credentials: $APP_USERNAME / $APP_PASSWORD"
echo ""
echo "Test with:"
echo "curl -u $APP_USERNAME:$APP_PASSWORD http://$HOST:8000/health"
echo ""
echo "View logs:"
echo "ssh -i $SSH_KEY -p $PORT $USER_HOST 'tail -f ~/geoclip.log'"
