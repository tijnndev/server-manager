#!/bin/bash

set -e

echo "Starting server manager setup..."

echo "Cloning GitHub repository into /etc/server-manager..."
git clone https://github.com/tijnndev/server-manager.git /etc/server-manager

cd /etc/server-manager

echo "Installing Python dependencies..."
source venv/bin/activate || python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

echo "Setting up the database..."
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS server_monitor;"

echo "Initializing Flask-Migrate..."
flask db migrate
flask db upgrade

echo "Setting up the service..."

SERVICE_PATH="/etc/systemd/system/server-manager.service"

SERVICE_CONTENT="[Unit]
Description=Server Manager Flask App
After=network.target

[Service]
WorkingDirectory=/etc/server-manager/
Environment="PATH=/etc/server-manager/venv/"
ExecStart=/etc/server-manager/venv/bin/gunicorn --workers 3 --bind 0.0.0.0:7001 app:app
Restart=always

[Install]
WantedBy=multi-user.target"

echo "$SERVICE_CONTENT" > $SERVICE_PATH

echo "Reloading systemd..."
systemctl daemon-reload

echo "Enabling and starting the service..."
systemctl enable server-manager
systemctl start server-manager

echo "Server Manager setup complete! The service is now running."
