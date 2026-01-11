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
ssh -i "$SSH_KEY" -p "$PORT" "$USER_HOST" "mkdir -p ~/Documents/geoinfer/prod-gpu-api"

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
    "$USER_HOST:~/Documents/geoinfer/prod-gpu-api/"

# No need to sync src/ - standalone GPU server

# Install dependencies and run server
echo "🐍 Installing dependencies and starting server..."
ssh -i "$SSH_KEY" -p "$PORT" "$USER_HOST" bash << EOF
set -e
cd ~/Documents/geoinfer/prod-gpu-api

# Create virtual environment if it doesn't exist or is broken
if [ ! -f ".venv/bin/activate" ]; then
    echo "🐍 Creating virtual environment..."
    rm -rf .venv  # Remove broken venv if exists
    if ! python3 -m venv .venv 2>/dev/null; then
        echo ""
        echo "❌ Failed to create virtual environment!"
        echo "   Please install python3-venv first by running:"
        echo ""
        echo "   sudo apt install python3.12-venv"
        echo ""
        echo "   Then run this deploy script again."
        exit 1
    fi
fi

# Activate venv and install dependencies
source .venv/bin/activate

# Upgrade pip
echo "📦 Upgrading pip..."
pip install --quiet --upgrade pip

# Install PyTorch nightly with CUDA 12.4 (for Blackwell sm_100+ support)
echo "🔥 Installing PyTorch nightly with CUDA 12.4..."
pip install --quiet --pre torch --index-url https://download.pytorch.org/whl/nightly/cu124
pip install --quiet --pre torchvision --index-url https://download.pytorch.org/whl/nightly/cu124 --no-deps

# Install other dependencies from requirements.txt
echo "📦 Installing other dependencies..."
pip install --quiet -r requirements.txt

# Install additional tools
echo "📦 Installing additional tools..."
pip install --quiet supervisor

# Create .env file
cat > .env << ENVFILE
APP_USERNAME=$APP_USERNAME
APP_PASSWORD=$APP_PASSWORD
HOST=0.0.0.0
PORT=8000
ENVFILE

# Find ngrok path (installed via apt or snap)
if [ -f "/snap/bin/ngrok" ]; then
    NGROK_BIN="/snap/bin/ngrok"
elif [ -f "/usr/bin/ngrok" ]; then
    NGROK_BIN="/usr/bin/ngrok"
elif command -v ngrok &>/dev/null; then
    NGROK_BIN=\$(command -v ngrok)
else
    echo "❌ ngrok not found! Please install it: sudo snap install ngrok"
    exit 1
fi
echo "📍 Using ngrok at: \$NGROK_BIN"

# Create supervisor config for 24/7 auto-restart
echo "⚙️  Setting up supervisor for auto-restart..."
DEPLOY_DIR="\$HOME/Documents/geoinfer/prod-gpu-api"
SUPERVISOR_DIR="\$HOME/.supervisor"
mkdir -p \$SUPERVISOR_DIR/conf.d

# Write config with expanded paths (supervisor doesn't expand shell vars)
cat > \$SUPERVISOR_DIR/conf.d/geoclip.conf << SUPERVISORCONF
[program:geoclip]
command=\$DEPLOY_DIR/.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8000
directory=\$DEPLOY_DIR
autostart=true
autorestart=true
startretries=10
stderr_logfile=\$DEPLOY_DIR/geoclip-error.log
stdout_logfile=\$DEPLOY_DIR/geoclip.log
environment=PATH="\$DEPLOY_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin"

[program:ngrok]
command=\$NGROK_BIN http 8000 --log=stdout
directory=\$DEPLOY_DIR
autostart=true
autorestart=true
startretries=10
stderr_logfile=\$DEPLOY_DIR/ngrok-error.log
stdout_logfile=\$DEPLOY_DIR/ngrok.log
environment=PATH="/snap/bin:/usr/local/bin:/usr/bin:/bin"
SUPERVISORCONF

echo "📄 Supervisor config written:"
cat \$SUPERVISOR_DIR/conf.d/geoclip.conf

# Create main supervisor config if needed
if [ ! -f "\$SUPERVISOR_DIR/supervisord.conf" ]; then
    cat > \$SUPERVISOR_DIR/supervisord.conf << MAINCONF
[unix_http_server]
file=\$SUPERVISOR_DIR/supervisor.sock

[supervisord]
logfile=\$SUPERVISOR_DIR/supervisord.log
logfile_maxbytes=50MB
logfile_backups=10
loglevel=info
pidfile=\$SUPERVISOR_DIR/supervisord.pid
nodaemon=false

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix://\$SUPERVISOR_DIR/supervisor.sock

[include]
files = \$SUPERVISOR_DIR/conf.d/*.conf
MAINCONF
fi

# Start supervisord if not running
if ! pgrep -f "supervisord.*\$SUPERVISOR_DIR" > /dev/null; then
    echo "🚀 Starting supervisord..."
    .venv/bin/supervisord -c \$SUPERVISOR_DIR/supervisord.conf
    sleep 2
fi

# Restart all services
echo "🔄 Restarting services..."
.venv/bin/supervisorctl -c \$SUPERVISOR_DIR/supervisord.conf reread
.venv/bin/supervisorctl -c \$SUPERVISOR_DIR/supervisord.conf update
.venv/bin/supervisorctl -c \$SUPERVISOR_DIR/supervisord.conf restart geoclip
.venv/bin/supervisorctl -c \$SUPERVISOR_DIR/supervisord.conf restart ngrok

# Wait for services to start
sleep 5

# Check if server is running
if .venv/bin/supervisorctl -c \$SUPERVISOR_DIR/supervisord.conf status geoclip | grep RUNNING > /dev/null; then
    echo "✅ Server started successfully with auto-restart enabled"
    .venv/bin/supervisorctl -c \$SUPERVISOR_DIR/supervisord.conf status
else
    echo "❌ Server failed to start. Check logs:"
    tail -50 \$DEPLOY_DIR/geoclip.log
    tail -50 \$DEPLOY_DIR/geoclip-error.log
    exit 1
fi

# Get ngrok public URL
echo ""
echo "🌐 Getting ngrok public URL..."
sleep 3
NGROK_URL=\$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | grep -o '"public_url":"[^"]*"' | head -1 | cut -d'"' -f4)
if [ -n "\$NGROK_URL" ]; then
    echo "🔗 Public URL: \$NGROK_URL"
else
    echo "⚠️  Could not get ngrok URL. Check ngrok logs or visit http://localhost:4040"
fi
EOF

echo ""
echo "✅ Deployment complete!"
echo "🌐 Local: http://$HOST:8000"
echo "🔐 Credentials: $APP_USERNAME / $APP_PASSWORD"
echo ""
echo "Get ngrok URL:"
echo "ssh -i $SSH_KEY -p $PORT $USER_HOST 'curl -s http://localhost:4040/api/tunnels | grep -o \"public_url.*\" | head -1'"
echo ""
echo "View logs:"
echo "ssh -i $SSH_KEY -p $PORT $USER_HOST 'tail -f ~/Documents/geoinfer/prod-gpu-api/geoclip.log'"
echo "ssh -i $SSH_KEY -p $PORT $USER_HOST 'tail -f ~/Documents/geoinfer/prod-gpu-api/ngrok.log'"
