#!/bin/bash
# CertifyPro Deployment Automation Script for AWS EC2

# Exit immediately if any command returns non-zero status
set -e

echo "============================================="
echo "🚀 Starting CertifyPro Deployment on AWS EC2"
echo "============================================="

# 1. Pull latest code from main branch
echo "📥 Fetching latest codebase from origin main..."
if [ -d ".git" ]; then
    git pull origin main
else
    echo "⚠️ Warning: Not a git repository. Skipping git pull."
fi

# 2. Activate virtual environment if it exists, otherwise create it
if [ -f "venv/bin/activate" ]; then
    echo "🐍 Activating existing Python virtual environment..."
    source venv/bin/activate
elif [ -d "venv" ]; then
    echo "⚠️ Virtual environment directory found but activation file missing."
else
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
fi

# 3. Upgrade Pip and install dependencies
echo "📦 Installing and updating dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. Restart application
if command -v systemctl &>/dev/null && systemctl is-active --quiet certifypro.service; then
    echo "🔄 Restarting systemd service (certifypro.service)..."
    sudo systemctl restart certifypro.service
elif command -v docker &>/dev/null && [ -f "docker-compose.yml" ]; then
    echo "🐳 Rebuilding and restarting Docker containers..."
    docker-compose down
    docker-compose up -d --build
else
    echo "⚙️ No standard service manager found. Restarting app.py manually in background..."
    # Find and kill old app process if running
    PID=$(pgrep -f "app.py" || true)
    if [ ! -z "$PID" ]; then
        echo "🛑 Killing old app.py process ($PID)..."
        kill -9 $PID
    fi
    # Run in background redirecting output to logs
    nohup python3 app.py > app.log 2>&1 &
    echo "✅ Application restarted in background (PID: $!). Logs written to app.log"
fi

echo "============================================="
echo "✅ CertifyPro Deployment Completed Successfully!"
echo "============================================="
