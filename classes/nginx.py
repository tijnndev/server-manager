import socket
import subprocess
import os

class NginxManager:
    def __init__(self, process):
        self.process = process
        self.domain = process.domain or process.name

    def get_nginx_file_path(self):
        return f'/etc/nginx/sites-available/{self.domain}'

    def get_nginx_enabled_path(self):
        return f'/etc/nginx/sites-enabled/{self.domain}'

    def get_cert_path(self):
        return f'/etc/letsencrypt/live/{self.domain}/fullchain.pem'

    def set_domain(self, domain_name):
        self.domain = domain_name
        self.process.domain = domain_name

    def create_nginx(self):
        local_ip = socket.gethostbyname(socket.gethostname())
        nginx_content = f"""server {{
    listen 80;
    server_name {self.domain};

    location / {{
        proxy_pass http://{local_ip}:{self.process.port_id + 8000}/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}"""
        
        nginx_file_path = self.get_nginx_file_path()
        nginx_enabled_path = self.get_nginx_enabled_path()

        subprocess.run(["sudo", "sh", "-c", f"echo '{nginx_content}' > {nginx_file_path}"])

        if not os.path.exists(nginx_enabled_path):
            subprocess.run(["sudo", "ln", "-s", nginx_file_path, nginx_enabled_path])

        subprocess.run(["sudo", "systemctl", "reload", "nginx"])
        return nginx_content

    def add_cert(self):
        subprocess.run(["sudo", "certbot", "--nginx", "-d", self.domain, "--non-interactive"])
        subprocess.run(["sudo", "systemctl", "reload", "nginx"])

    def renew_cert(self):
        subprocess.run(["sudo", "certbot", "renew", "--cert-name", self.domain, "--non-interactive"])
        subprocess.run(["sudo", "systemctl", "reload", "nginx"])

    def delete_cert(self):
        subprocess.run(["sudo", "certbot", "delete", "--cert-name", self.domain, "--non-interactive"])

        nginx_content = self.create_nginx()
        subprocess.run(["sudo", "sh", "-c", f"echo '{nginx_content}' > {self.get_nginx_file_path()}"])
        subprocess.run(["sudo", "systemctl", "reload", "nginx"])

    def remove_nginx(self):
        nginx_enabled_path = self.get_nginx_enabled_path()
        nginx_file_path = self.get_nginx_file_path()

        if os.path.exists(nginx_enabled_path):
            os.remove(nginx_enabled_path)
        if os.path.exists(nginx_file_path):
            os.remove(nginx_file_path)

        subprocess.run(["sudo", "systemctl", "reload", "nginx"])

    def restart_nginx(self):
        subprocess.run(["sudo", "systemctl", "restart", "nginx"])

    def save_nginx_config(self, new_config):
        subprocess.run(["sudo", "sh", "-c", f"echo '{new_config.strip()}' > {self.get_nginx_file_path()}"], check=True)
