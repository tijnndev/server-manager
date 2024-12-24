#!/bin/bash

set -e

echo "Starting server manager setup..."

# Step 1: Check if the folder exists
if [ -d "/etc/server-manager" ]; then
  echo "/etc/server-manager already exists."
  read -p "Do you want to overwrite the existing folder? (y/n): " choice
  if [[ "$choice" != "y" ]]; then
    echo "Exiting script. No changes made."
    exit 0
  fi
  echo "Removing existing directory..."
  rm -rf /etc/server-manager
fi

# Step 2: Clone the GitHub repository
echo "Cloning GitHub repository into /etc/server-manager..."
git clone https://github.com/tijnndev/server-manager.git /etc/server-manager

cd /etc/server-manager

# Step to copy .env.example to .env
echo "Copying .env.example to .env..."
cp .env.example .env

# Step 3: Set up Python virtual environment and install dependencies
echo "Installing Python dependencies..."
if [ ! -d "venv" ]; then
  python3 -m venv venv
  echo "Virtual environment created."
fi
source venv/bin/activate
pip install -r requirements.txt

# Step 4: Database setup prompt
read -p "Do you want to import the database (server-monitor)? (y/n): " import_db
if [ "$import_db" == "y" ]; then
    echo "Please provide MySQL credentials to import the database."

    # Step 4.1: Get MySQL credentials
    read -p "Enter MySQL username: " db_user
    read -sp "Enter MySQL password: " db_password
    echo

    # Step 4.2: Import the database
    echo "Setting up the database..."
    mysql -u "$db_user" -p"$db_password" -e "CREATE DATABASE IF NOT EXISTS \`server-monitor\`;"
else
    echo "Skipping database import."
fi

# Step 5: Service setup
echo "Setting up the service..."
SERVICE_PATH="/etc/systemd/system/server-manager.service"

SERVICE_CONTENT="[Unit]
Description=Server Manager Flask App
After=network.target

[Service]
WorkingDirectory=/etc/server-manager/
Environment=\"PATH=/etc/server-manager/venv/\"
ExecStart=/etc/server-manager/venv/bin/gunicorn --workers 3 --bind 0.0.0.0:7001 app:app
Restart=always

[Install]
WantedBy=multi-user.target"

echo "$SERVICE_CONTENT" > $SERVICE_PATH

# Step 6: Reload systemd to recognize the new service
echo "Reloading systemd..."
systemctl daemon-reload

read -p "Do you want to edit the .env file? (y/n): " edit_env
if [ "$edit_env" == "y" ]; then
    echo "Step 1: Please edit the /etc/server-manager/.env file with the right database credentials to allow the service to create processes"
    echo "Step 2: Go in to /etc/server-manager/ and execute: source venv/bin/activate"
    echo "Step 3: Execute the command: flask db migrate"
    echo ""
    echo "Final step: start the process:"
    echo "systemctl enable server-manager"
    echo "systemctl start server-manager"
else
    echo "If there shows an error after this, edit the /etc/server-manager/.env with the db access info"
    flask db migrate
    flask db upgrade

    echo "Enabling and starting the service..."
    systemctl enable server-manager
    systemctl start server-manager
fi


echo "Server Manager setup complete! The service is now running."
