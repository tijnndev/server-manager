import time
import socket
import subprocess
from flask import Blueprint, redirect, request, render_template
import os
from db import db
from decorators import owner_or_subuser_required, owner_required
from utils import find_process_by_name

nginx_routes = Blueprint('nginx', __name__)

@nginx_routes.route('/<name>', methods=['GET', 'POST'])
@owner_or_subuser_required()
def nginx(name):
    process = find_process_by_name(name)
    
    nginx_file_path = f'/etc/nginx/sites-available/{process.domain or name}'
    nginx_enabled_path = f'/etc/nginx/sites-enabled/{process.domain or name}'
    cert_path = f'/etc/letsencrypt/live/{process.domain or name}/fullchain.pem'

    if request.method == 'POST':
        action = request.form.get("action")
        domain_name = request.form.get("domain_name", process.domain or name)
        nginx_enabled_path = f'/etc/nginx/sites-enabled/{domain_name}'
        process.domain = domain_name
        db.session.add(process)
        db.session.commit()

        cert_path = f'/etc/letsencrypt/live/{domain_name}/fullchain.pem'

        if action == "create_nginx":
            local_ip = socket.gethostbyname(socket.gethostname())

            default_nginx_content = f"""server {{
    listen 80;
    server_name {domain_name};

    location / {{
        proxy_pass http://{local_ip}:{process.port_id + 8000}/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}"""
            
            with open(nginx_file_path, 'w') as file:
                file.write(default_nginx_content)
            
            if not os.path.exists(nginx_enabled_path):
                os.symlink(nginx_file_path, nginx_enabled_path)

            subprocess.run(["sudo", "systemctl", "reload", "nginx"])
            return render_template('nginx/index.html', service=process, nginx_content=default_nginx_content)

        elif action == "add_cert":
            subprocess.run(["sudo", "certbot", "--nginx", "-d", domain_name, "--non-interactive"])
            subprocess.run(["sudo", "systemctl", "reload", "nginx"])
        
        elif action == "renew_cert":
            subprocess.run(["sudo", "certbot", "renew", "--cert-name", domain_name, "--non-interactive"])
            subprocess.run(["sudo", "systemctl", "reload", "nginx"])

        elif action == "delete_cert":
            subprocess.run(["sudo", "certbot", "delete", "--cert-name", domain_name, "--non-interactive"])

            local_ip = socket.gethostbyname(socket.gethostname())
            default_nginx_content = f"""server {{
    listen 80;
    server_name {domain_name};

    location / {{
        proxy_pass http://{local_ip}:{process.port_id + 8000}/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}"""

            
            with open(nginx_file_path, 'w') as file:
                file.write(default_nginx_content)

            
            subprocess.run(["sudo", "systemctl", "reload", "nginx"])
        elif action == "remove_nginx":
            if os.path.exists(nginx_enabled_path):
                os.remove(nginx_enabled_path)
            if os.path.exists(nginx_file_path):
                os.remove(nginx_file_path)
            subprocess.run(["sudo", "systemctl", "reload", "nginx"])
        
        elif action == "restart_nginx":
            redirect('/')
            time.sleep(2)
            subprocess.run(["sudo", "systemctl", "restart", "nginx"])
    
    cert_exists = os.path.exists(cert_path)
    
    nginx_content = None
    if os.path.exists(nginx_file_path):
        with open(nginx_file_path, 'r') as file:
            nginx_content = file.read()

    return render_template('nginx/index.html', service=process, nginx_content=nginx_content, cert_exists=cert_exists)

