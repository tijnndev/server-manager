import time
import socket
import subprocess
from flask import Blueprint, redirect, request, render_template
import os
from db import db
from decorators import owner_or_subuser_required
from utils import find_process_by_name

nginx_routes = Blueprint('nginx', __name__)


@nginx_routes.route('/<name>', methods=['GET', 'POST'])
@owner_or_subuser_required()
def nginx(name):
    process = find_process_by_name(name)
    domain_name = request.form.get("domain_name", process.domain or name)
    
    process.domain = domain_name
    db.session.commit()

    nginx_file_path = f'/etc/nginx/sites-available/{domain_name}'
    nginx_enabled_path = f'/etc/nginx/sites-enabled/{domain_name}'
    cert_path = f'/etc/letsencrypt/live/{domain_name}/fullchain.pem'

    if request.method == 'POST':
        action = request.form.get("action")

        action_handlers = {
            "create_nginx": lambda: create_nginx_config(process, domain_name, nginx_file_path, nginx_enabled_path),
            "add_cert": lambda: run_certbot(["--nginx", "-d", domain_name]),
            "renew_cert": lambda: run_certbot(["renew", "--cert-name", domain_name]),
            "delete_cert": lambda: delete_cert(process, domain_name, nginx_file_path),
            "remove_nginx": lambda: remove_nginx_config(nginx_file_path, nginx_enabled_path),
            "restart_nginx": restart_nginx,
            "save_nginx": lambda: save_nginx_config(request.form.get("nginx_config"), nginx_file_path),
        }

        if action in action_handlers:
            action_handlers[action]()

    return render_template('nginx/index.html',
                           page_title="Nginx",
                           process=process,
                           nginx_content=read_nginx_config(nginx_file_path),
                           cert_exists=os.path.exists(cert_path))


def create_nginx_config(process, domain_name, nginx_file_path, nginx_enabled_path):
    """Create a basic Nginx reverse proxy configuration."""
    local_ip = socket.gethostbyname(socket.gethostname())
    config = f"""server {{
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

    write_nginx_config(nginx_file_path, config)
    
    if not os.path.exists(nginx_enabled_path):
        subprocess.run(["sudo", "ln", "-s", nginx_file_path, nginx_enabled_path], check=True)

    restart_nginx()
    return render_template('nginx/index.html', process=process, nginx_content=config)


def delete_cert(process, domain_name, nginx_file_path):
    """Delete SSL certificate and revert to HTTP configuration."""
    run_certbot(["delete", "--cert-name", domain_name])
    create_nginx_config(process, domain_name, nginx_file_path, f'/etc/nginx/sites-enabled/{domain_name}')


def remove_nginx_config(nginx_file_path, nginx_enabled_path):
    """Remove Nginx configuration files and reload Nginx."""
    for path in [nginx_enabled_path, nginx_file_path]:
        if os.path.exists(path):
            os.remove(path)
    restart_nginx()


def save_nginx_config(new_config, nginx_file_path):
    """Save new Nginx configuration from the form input."""
    if new_config:
        write_nginx_config(nginx_file_path, new_config.strip())


def run_certbot(args):
    """Run Certbot commands for managing SSL certificates."""
    subprocess.run(["sudo", "certbot"] + args + ["--non-interactive"], check=True)
    restart_nginx()


def restart_nginx():
    """Restart Nginx service."""
    time.sleep(2)
    subprocess.run(["sudo", "systemctl", "restart", "nginx"], check=True)
    return redirect('/')


def write_nginx_config(file_path, content):
    """Write content to an Nginx configuration file."""
    subprocess.run(["sudo", "sh", "-c", f"echo '{content}' > {file_path}"], check=True)


def read_nginx_config(file_path):
    """Read Nginx configuration file content."""
    return open(file_path).read() if os.path.exists(file_path) else None
