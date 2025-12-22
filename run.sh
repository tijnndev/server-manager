#!/bin/bash

set -e

echo "Starting server manager setup..."

check_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo $NAME
        if [[ "$NAME" == "Ubuntu" || "$NAME" == "Manjaro Linux" ]]; then
            return 1
        else
            return 0
        fi
    else
        echo "Unable to detect the operating system."
        return 1
    fi
}

if check_os; then
    echo "This script only supports Ubuntu or Manjaro Linux. Exiting."
    exit 1
fi

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

echo "Cloning GitHub repository into /etc/server-manager..."
git clone https://github.com/tijnndev/server-manager.git /etc/server-manager

cd /etc/server-manager

echo "Copying .env.example to .env..."
cp .env.example .env

echo "Installing Python dependencies..."
if [ ! -d "venv" ]; then
  python3.12 -m venv venv
  echo "Virtual environment created."
fi
source venv/bin/activate
pip install -r requirements.txt

read -p "Do you want to import the database (server-monitor)? (y/n): " import_db
if [ "$import_db" == "y" ]; then
    echo "Please provide MySQL credentials to import the database."

    read -p "Enter MySQL username: " db_user
    read -sp "Enter MySQL password: " db_password
    echo

    echo "Setting up the database..."
    mysql -u "$db_user" -p"$db_password" -e "CREATE DATABASE IF NOT EXISTS \`server-monitor\`;"
else
    echo "Skipping database import."
fi

read -p "Do you want to use Node.js? (y/n): " use_nodejs
if [ "$use_nodejs" == "y" ]; then
  if ! command -v npm &> /dev/null; then
    echo "npm not found, installing npm..."
    apt-get update
    apt-get install -y npm
  else
    echo "npm is already installed."
  fi
else
  echo "Skipping Node.js setup."
fi

echo "Setting up the process..."
PROCESS_PATH="/etc/systemd/system/server-manager.service"

PROCESS_CONTENT="[Unit]
Description=Server Manager Flask App
After=network.target

[Service]
WorkingDirectory=/etc/server-manager/
Environment=\"PATH=/etc/server-manager/venv/\"
ExecStart=/etc/server-manager/venv/bin/gunicorn -c /etc/server-manager/gunicorn_config.py app:app
Restart=always

[Install]
WantedBy=multi-user.target"

echo "$PROCESS_CONTENT" > $PROCESS_PATH

echo "Reloading systemd..."
systemctl daemon-reload

read -p "Do you want to edit the .env file? (y/n): " edit_env
if [ "$edit_env" == "y" ]; then
    echo ""
    echo ""
    echo "Step 1: Please edit the /etc/server-manager/.env file with the right database credentials to allow the process to create processes"
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

    echo "Enabling and starting the process..."
    systemctl enable server-manager
    systemctl start server-manager
fi


echo "Server Manager setup complete! The process is now running."
