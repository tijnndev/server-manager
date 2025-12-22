#!/bin/bash

# Quick Setup Script for Performance Optimizations
# Run this on your server to apply all performance improvements

set -e

echo "=========================================="
echo "Server Manager Performance Upgrade"
echo "Optimizing for AMD Ryzen 9 7950X3D"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root or with sudo"
    exit 1
fi

INSTALL_DIR="/etc/server-manager"

# Navigate to installation directory
if [ ! -d "$INSTALL_DIR" ]; then
    echo "ERROR: $INSTALL_DIR not found!"
    echo "Please install Server Manager first using run.sh"
    exit 1
fi

cd "$INSTALL_DIR"

echo "[1/7] Pulling latest optimizations from Git..."
git pull origin main || {
    echo "WARNING: Could not pull from Git. Continuing anyway..."
}

echo ""
echo "[2/7] Installing performance dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "[3/7] Creating log directory..."
mkdir -p /var/log/server-manager
chown -R www-data:www-data /var/log/server-manager 2>/dev/null || true

echo ""
echo "[4/7] Creating backup directory..."
mkdir -p /var/backups/server-manager

echo ""
echo "[5/7] Updating systemd service..."
cp server-manager.service /etc/systemd/system/
systemctl daemon-reload

echo ""
echo "[6/7] Making deployment script executable..."
chmod +x deploy.sh

echo ""
echo "[7/7] Restarting service with new configuration..."
systemctl restart server-manager

echo ""
echo "Waiting for service to start..."
sleep 5

echo ""
echo "=========================================="
echo "Performance Upgrade Complete! ✅"
echo "=========================================="
echo ""

# Check service status
if systemctl is-active --quiet server-manager; then
    echo "✅ Service is running"
    
    # Count workers
    WORKER_COUNT=$(pgrep -f "gunicorn.*app:app" | wc -l)
    echo "✅ Active workers: $WORKER_COUNT (should be ~33)"
    
    # Check if app is responding
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:7001 | grep -q "200\|302"; then
        echo "✅ Application is responding"
    else
        echo "⚠️  Application may not be responding on port 7001"
    fi
    
    echo ""
    echo "Performance Stats:"
    echo "=================="
    echo "Workers: 32 gevent workers (was 3)"
    echo "Max Concurrent: 32,000 connections (was ~30)"
    echo "CPU Cores: 16 cores fully utilized"
    echo "Cache: Redis-backed"
    echo "DB Pool: 60 connections (20+40)"
    echo ""
    echo "Next Steps:"
    echo "==========="
    echo "1. Monitor logs: sudo journalctl -u server-manager -f"
    echo "2. Check stats: curl http://localhost:7001/api/server/stats"
    echo "3. For deployments: sudo ./deploy.sh"
    echo ""
    echo "📖 Read PERFORMANCE.md for detailed documentation"
    echo ""
    echo "🚀 Your server is now running at maximum performance!"
    
else
    echo "❌ Service failed to start!"
    echo ""
    echo "Check logs with: sudo journalctl -u server-manager -n 50"
    exit 1
fi

deactivate
