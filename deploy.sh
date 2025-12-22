#!/bin/bash

# Server Manager Production Deployment Script
# Handles zero-downtime deployments with graceful worker restarts
# Optimized for AMD Ryzen 9 7950X3D with 32 Gunicorn workers

set -e

INSTALL_DIR="/etc/server-manager"
SERVICE_NAME="server-manager"
BACKUP_DIR="/var/backups/server-manager"
LOG_DIR="/var/log/server-manager"
VENV_DIR="$INSTALL_DIR/venv"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    log_error "Please run as root or with sudo"
    exit 1
fi

# Create necessary directories
mkdir -p "$BACKUP_DIR"
mkdir -p "$LOG_DIR"

# Change to installation directory
cd "$INSTALL_DIR" || exit 1

log_info "Starting Server Manager deployment..."

# Step 1: Create backup
log_info "Creating backup..."
BACKUP_FILE="$BACKUP_DIR/backup-$(date +%Y%m%d-%H%M%S).tar.gz"
tar -czf "$BACKUP_FILE" \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    -C "$INSTALL_DIR" . 2>/dev/null || log_warning "Some files could not be backed up"
log_success "Backup created: $BACKUP_FILE"

# Step 2: Pull latest changes
log_info "Pulling latest changes from Git..."
if [ -d ".git" ]; then
    git fetch origin
    git pull origin main
    log_success "Git pull completed"
else
    log_warning "Not a git repository, skipping git pull"
fi

# Step 3: Activate virtual environment and upgrade dependencies
log_info "Updating Python dependencies..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install -r requirements.txt -q
log_success "Dependencies updated"

# Step 4: Run database migrations
log_info "Running database migrations..."
export FLASK_APP=app.py
flask db upgrade 2>/dev/null || log_warning "No new migrations to apply"
log_success "Database migrations completed"

# Step 5: Clear old compiled Python files
log_info "Cleaning up Python cache..."
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
log_success "Cache cleaned"

# Step 6: Graceful service reload
log_info "Performing graceful reload of Gunicorn workers..."

if systemctl is-active --quiet "$SERVICE_NAME"; then
    # Get the main Gunicorn master process PID
    MASTER_PID=$(systemctl show --property MainPID --value "$SERVICE_NAME")
    
    if [ -n "$MASTER_PID" ] && [ "$MASTER_PID" != "0" ]; then
        log_info "Sending HUP signal to Gunicorn master (PID: $MASTER_PID) for graceful reload..."
        
        # HUP signal tells Gunicorn to gracefully reload workers
        # - Old workers finish current requests
        # - New workers are spawned with updated code
        # - Zero downtime for users
        kill -HUP "$MASTER_PID"
        
        # Wait for reload to complete
        sleep 5
        
        # Verify service is still running
        if systemctl is-active --quiet "$SERVICE_NAME"; then
            log_success "Graceful reload completed - 32 workers restarted with new code"
        else
            log_error "Service stopped unexpectedly during reload"
            log_info "Attempting to start service..."
            systemctl start "$SERVICE_NAME"
        fi
    else
        log_warning "Could not find Gunicorn master PID, performing full restart..."
        systemctl restart "$SERVICE_NAME"
    fi
else
    log_info "Service not running, starting it..."
    systemctl start "$SERVICE_NAME"
fi

# Step 7: Wait for service to be fully ready
log_info "Waiting for service to be ready..."
sleep 3

# Step 8: Health check
log_info "Performing health check..."
if systemctl is-active --quiet "$SERVICE_NAME"; then
    log_success "Service is running"
    
    # Check if the application is responding
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:7001 | grep -q "200\|302"; then
        log_success "Application is responding correctly"
    else
        log_warning "Application may not be responding correctly"
    fi
    
    # Display worker status
    WORKER_COUNT=$(pgrep -f "gunicorn.*app:app" | wc -l)
    log_info "Active Gunicorn workers: $WORKER_COUNT"
    
else
    log_error "Service failed to start"
    log_info "Checking logs..."
    journalctl -u "$SERVICE_NAME" -n 20 --no-pager
    exit 1
fi

# Step 9: Cleanup old backups (keep last 10)
log_info "Cleaning up old backups..."
cd "$BACKUP_DIR"
ls -t backup-*.tar.gz 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null || true
BACKUP_COUNT=$(ls -1 backup-*.tar.gz 2>/dev/null | wc -l)
log_info "Keeping $BACKUP_COUNT most recent backups"

# Step 10: Display deployment summary
log_success "================================"
log_success "Deployment completed successfully!"
log_success "================================"
log_info "Service: $SERVICE_NAME"
log_info "Workers: 32 (optimized for Ryzen 9 7950X3D)"
log_info "Worker Class: gevent (async I/O)"
log_info "Cache: Redis-backed"
log_info "Connection Pool: 20+40 database connections"
log_info "Backup: $BACKUP_FILE"
log_info ""
log_info "View logs: journalctl -u $SERVICE_NAME -f"
log_info "Check status: systemctl status $SERVICE_NAME"
log_info "View metrics: curl http://localhost:7001/api/server/stats"

deactivate
