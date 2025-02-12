import shutil
import time, yaml
import subprocess
from flask import Blueprint, jsonify, redirect, request, render_template, Response, url_for
import os, json, re
from datetime import datetime
from db import db
from models.process import Process
from models.discord_integration import DiscordIntegration
from utils import find_process_by_name, get_service_status

nginx_routes = Blueprint('nginx', __name__)

SERVICES_DIRECTORY = 'active-servers'
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, 'active-servers')

def is_within_base_dir(path, base=ACTIVE_SERVERS_DIR):
    abs_base = os.path.abspath(base)
    abs_path = os.path.abspath(path)
    return os.path.commonpath([abs_base]) == os.path.commonpath([abs_base, abs_path])


def load_services():
    services = {}

    processes = Process.query.all()

    for process in processes:
        response = get_service_status(process.name)

        if "error" in response:
            print(f"Error fetching status for {process.name}: {response['error']}")
        else:
            services[process.name] = {
                "id": process.id,
                "type": process.type,
                "command": process.command,
                "file_location": process.file_location,
                "name": process.name,
                "status": response["status"]
            }

    return services

import socket

@nginx_routes.route('/<name>', methods=['GET', 'POST'])
def nginx(name):
    process = find_process_by_name(name)
    nginx_file_path = f'/etc/nginx/sites-available/{process.domain}'
    nginx_enabled_path = f'/etc/nginx/sites-enabled/{process.domain}'
    cert_path = f'/etc/letsencrypt/live/{process.domain}/fullchain.pem'

    if request.method == 'POST':
        action = request.form.get("action")
        domain_name = request.form.get("domain_name", process.domain)
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
            subprocess.run(["sudo", "certbot", "--nginx", "-d", domain_name])
            subprocess.run(["sudo", "systemctl", "reload", "nginx"])
        
        elif action == "renew_cert":
            subprocess.run(["sudo", "certbot", "renew"])
            subprocess.run(["sudo", "systemctl", "reload", "nginx"])

        elif action == "delete_cert":
            subprocess.run(["sudo", "certbot", "delete", "--cert-name", domain_name, "--non-interactive"])

        elif action == "remove_nginx":
            if os.path.exists(nginx_enabled_path):
                os.remove(nginx_enabled_path)
            if os.path.exists(nginx_file_path):
                os.remove(nginx_file_path)
            subprocess.run(["sudo", "systemctl", "reload", "nginx"])
    
    cert_exists = os.path.exists(cert_path)
    
    nginx_content = None
    if os.path.exists(nginx_file_path):
        with open(nginx_file_path, 'r') as file:
            nginx_content = file.read()

    return render_template('nginx/index.html', service=process, nginx_content=nginx_content, cert_exists=cert_exists)



@nginx_routes.route('/add', methods=['POST'])
def add_service():
    data = request.json
    print(data)

    if data is None:
        return jsonify({"error": "Invalid or duplicate service name"}), 400

    services = load_services()
    service_name = data.get("name")

    if not service_name or service_name in services:
        return jsonify({"error": "Invalid or duplicate service name"}), 400

    service_dir = os.path.join(ACTIVE_SERVERS_DIR, service_name)

    if not is_within_base_dir(service_dir):
        return jsonify({"error": "Invalid service name or directory"}), 400
    
    if os.path.exists(service_dir):
        return jsonify({"error": "Service directory already exists"}), 400

    try:
        os.makedirs(service_dir, exist_ok=False)

        new_process = Process(
            name=service_name, # type: ignore
            command=data.get("command", ""), # type: ignore
            type=data.get("type", ""), # type: ignore
            file_location=service_dir, # type: ignore
            id="pending", # type: ignore
        )

        db.session.add(new_process)
        db.session.commit()

        compose_file_path = os.path.join(service_dir, 'docker-compose.yml')
        with open(compose_file_path, 'w') as f:
            f.write(f"""version: '3.7'

services:
  {service_name}:
    build:
      context: .
      dockerfile: Dockerfile
    volumes:
      - .:/app
    command: ["sh", "-c", {data.get("command", "")}]
    ports:
      - "{8000 + new_process.port_id}:{8000 + new_process.port_id}"
    environment:
      - COMMAND={data.get("command", "")}
            """)

        dockerfile_content = f"""
FROM {data.get("type", "python:3.9-slim")}
WORKDIR /app
COPY . /app
RUN pip install -r requirements.txt
CMD ["sh", "-c", "$COMMAND"]
"""
        dockerfile_path = os.path.join(service_dir, "Dockerfile")
        with open(dockerfile_path, "w") as f:
            f.write(dockerfile_content)

        os.chdir(service_dir)
        os.system('//usr/local/bin/docker-compose up -d')

        return jsonify({"message": "Service added and running in Docker container", "directory": service_dir})

    except OSError as e:
        return jsonify({"error": f"Failed to create service directory: {e}"}), 500
    except DockerException as e:
        return jsonify({"error": f"Failed to create Docker container: {e}"}), 500
    

@nginx_routes.route('/delete/<name>', methods=['POST'])
def delete(name):
    try:
        service = Process.query.filter_by(name=name).first()
        if not service:
            return jsonify({"error": "Service not found"}), 404

        service_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
        if os.path.exists(service_dir):
            try:
                os.chdir(service_dir)
                subprocess.run(['/usr/local/bin/docker-compose', 'down'], check=True)
                print(f"Service {name} stopped and removed successfully via docker-compose")
            except subprocess.CalledProcessError as e:
                print(f"Error stopping service {name}: {e}")
                return jsonify({"error": "Failed to stop service via docker-compose"}), 500

            shutil.rmtree(service_dir)
            print(f"Service directory {service_dir} removed successfully")
        
        db.session.delete(service)
        db.session.commit()

        return redirect('/')

    except Exception as e:
        print(f"Error deleting service: {e}")
        return jsonify({"error": str(e)}), 500


@nginx_routes.route('/start/<string:name>', methods=['POST'])
def start_service(name):
    service = find_process_by_name(name)
    if not service:
        return jsonify({"error": "Service not found"}), 404

    try:
        os.chdir(os.path.join(ACTIVE_SERVERS_DIR, name))
        
        subprocess.run(['//usr/local/bin/docker-compose', 'up', '-d'], check=True)

        time.sleep(2)

        return jsonify({"message": f"Service {name} started successfully.", "status": get_service_status(service.name), "ok": True})

    except subprocess.CalledProcessError as e:
        error_message = e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)
        return jsonify({"error": error_message, "ok": False}), 500
    except Exception as e:
        error_message = str(e)
        return jsonify({"error": error_message, "ok": False}), 500



@nginx_routes.route('/stop/<string:name>', methods=['POST'])
def stop_service(name):
    service = find_process_by_name(name)
    if not service:
        return jsonify({"error": "Service not found"}), 404

    try:
        os.chdir(os.path.join(ACTIVE_SERVERS_DIR, name))
        os.system('//usr/local/bin/docker-compose down')

        return jsonify({"message": f"Service {name} stopped successfully."})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

def calculate_uptime(startup_date):
    startup_datetime = datetime.fromisoformat(startup_date[:-1])
    current_time = datetime.now()

    uptime = current_time - startup_datetime

    seconds = int(uptime.total_seconds())

    weeks = seconds // (7 * 24 * 3600)
    days = (seconds % (7 * 24 * 3600)) // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60

    uptime_str = ''

    uptime_str += f"{weeks}w {days}d {hours}h {minutes}m {seconds}s"

    return uptime_str.strip()



@nginx_routes.route('/console/<string:name>', methods=['GET'])
def console(name):
    service = find_process_by_name(name)
    
    if not service:
        return jsonify({"error": "Service not found"}), 404
    
    response = get_service_status(service.name)

    try:
        status = response["status"]
    except KeyError:
        status = "Failed"
    return render_template('service/console.html', service=service, service_status=status)

@nginx_routes.route('/console/<service_name>/uptime')
def get_uptime(service_name):
    process = find_process_by_name(service_name)
    if not process:
        return jsonify({'error': 'Service not found'}), 404

    try:
        service_dir = os.path.join(ACTIVE_SERVERS_DIR, service_name)
        os.chdir(service_dir)

        result = subprocess.run(['docker-compose', 'ps', '-q'], capture_output=True, text=True, check=True)
        container_id = result.stdout.strip()

        if not container_id:
            return jsonify({'uptime': '0w 0d 0h 0m 0s', 'error': 'Service is not running.'})

        result = subprocess.run(['docker', 'inspect', '--format', '{{.State.StartedAt}}', container_id],
                                capture_output=True, text=True, check=True)
        startup_date = result.stdout.strip()

        uptime = calculate_uptime(startup_date)
        return jsonify({'uptime': uptime})

    except subprocess.CalledProcessError as e:
        return jsonify({'uptime': '0w 0d 0h 0m 0s', 'error': f"Failed to get service status: {e.stderr}"})
    except Exception as e:
        return jsonify({'uptime': '0w 0d 0h 0m 0s', 'error': str(e)})



@nginx_routes.route('/console/<string:name>/logs', methods=['GET'])
def stream_logs(name):
    service = find_process_by_name(name)
    if not service:
        return jsonify({"error": "Service not found"}), 404

    try:
        service_dir = os.path.join(ACTIVE_SERVERS_DIR, name)

        # Log command to fetch Docker logs
        logs_command = ['//usr/local/bin/docker-compose', 'logs', '--tail', '50']

        process = subprocess.Popen(
            logs_command,
            cwd=service_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1  # Set buffer size to line-buffered for real-time output
        )

        def generate():
            try:
                # Read stdout line-by-line to stream it immediately
                for line in process.stdout:
                    yield f"data: {colorize_log(line)}\n\n"
            except Exception as e:
                print(f"Error while streaming logs: {e}")
            finally:
                process.terminate()  # Ensure process is terminated after streaming
                process.wait()

        return Response(generate(), content_type='text/event-stream')

    except Exception as e:
        return jsonify({"error": str(e)}), 500



def colorize_log(log):
    ansi_escape = re.compile(r'\033\[(\d+(;\d+)*)m')
    log = ansi_escape.sub(lambda match: f'<span style="color: {ansi_to_html(match.group(1))};">', log)
    log = log.replace('\033[0m', '</span>')
    return log


def ansi_to_html(ansi_code):
    color_map = {
        "31": "red",
        "32": "green",
        "33": "yellow",
        "34": "blue",
        "35": "magenta",
        "36": "cyan",
        "37": "white",
    }
    return color_map.get(ansi_code.split(';')[0], "black")


# @nginx_routes.route('/console/<string:name>/send', methods=['POST'])
# def send_command(name):
#     service = find_process_by_name(name)
#     if not service or not request.json:
#         return jsonify({"error": "Service not found"}), 404

#     command = request.json.get('command')
#     if not command:
#         return jsonify({"error": "No command provided"}), 400

#     try:
#         container = client.containers.get(service.id)
#         exec_id = container.exec_run(command, tty=True, stdin=True)
#         return jsonify({"message": "Command executed", "output": exec_id.output.decode('utf-8')})
#     except Exception as e:
#         return jsonify({"error": str(e)}), 500
    
def ansi_to_html(ansi_code):
    """Map ANSI codes to HTML colors."""
    color_map = {
        '31': 'red',
        '32': 'green',
        '33': 'yellow',
        '34': 'blue',
        '35': 'magenta',
        '36': 'cyan',
        '37': 'white',
        '0': 'black',
    }
    codes = ansi_code.split(';')
    for code in codes:
        if code in color_map:
            return color_map[code]
    return 'black'

@nginx_routes.route('/settings/<string:name>', methods=['GET', 'POST'])
def settings(name):
    service = find_process_by_name(name)
    if not service:
        return render_template('service/settings.html', service=service)
    
    if request.method == 'POST':
        service.name = request.form.get('name')
        service.description = request.form.get('description')
        service.command = request.form.get('command')
        service.type = request.form.get('type')
        service.params = request.form.get('params', '')

        service_dir = os.path.join(ACTIVE_SERVERS_DIR, service.name)
        dockerfile_path = f'{service_dir}/Dockerfile'

        if not service.command:
            return print("Service command not found")
        
        service_dir = os.path.join(ACTIVE_SERVERS_DIR, service.name)
        compose_file_path = os.path.join(service_dir, 'docker-compose.yml')

        if os.path.exists(compose_file_path):
            with open(compose_file_path, 'r') as compose_file:
                compose_data = yaml.safe_load(compose_file)

            if name in compose_data.get('services', {}):
                compose_data['services'][name]['command'] = service.command.split()
            else:
                return f"Service '{name}' not found in docker-compose.yml", 404

            with open(compose_file_path, 'w') as compose_file:
                yaml.safe_dump(compose_data, compose_file, default_flow_style=False)

            print(f"docker-compose.yml for {service.name} updated with new command: {service.command}")
        else:
            print(f"docker-compose.yml for {service.name} not found")
            return f"docker-compose.yml for {service.name} not found", 404
        
        if os.path.exists(dockerfile_path):
            with open(dockerfile_path, 'r') as dockerfile:
                dockerfile_content = dockerfile.readlines()

            for idx, line in enumerate(dockerfile_content):
                if line.startswith("CMD") or line.startswith("ENTRYPOINT"):
                    dockerfile_content[idx] = f'CMD [{", ".join([f"\"{word}\"" for word in service.command.split()])}]\n'
                    break
            else:
                dockerfile_content.append(f'CMD {service.command.split()}\n')

            with open(dockerfile_path, 'w') as dockerfile:
                dockerfile.writelines(dockerfile_content)

            print(f'Dockerfile for {service.name} updated with new command: {service.command}')
        else:
            print(f'Dockerfile for {service.name} not found')
        
        db.session.add(service)
        db.session.commit()
        
        print('Service settings updated successfully!')
        return redirect(url_for('service.console', name=service.name))
    
    return render_template('service/settings.html', service=service)


@nginx_routes.route('/rebuild/<name>', methods=['POST'])
def rebuild(name):
    service = find_process_by_name(name)
    if not service:
        return redirect(url_for('service.index'))

    try:
        os.chdir(os.path.join(ACTIVE_SERVERS_DIR, name))
        os.system('//usr/local/bin/docker-compose build')

        return jsonify({"message": f"Service {name} rebuilt successfully!"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@nginx_routes.route('/discord/<string:name>', methods=['GET', 'POST'])
def discord(name):
    process = find_process_by_name(name)
    if request.method == 'POST':
        webhook_url = request.form.get('webhook_url')
        events = request.form.getlist('events')

        if webhook_url:
            integration = DiscordIntegration.query.filter_by(service_id=process.id).first()
            if not integration:
                integration = DiscordIntegration(service_id=process.id, webhook_url=webhook_url, events=json.dumps(events))
            else:
                integration.webhook_url = webhook_url
                integration.events_list = events

            db.session.add(integration)
            db.session.commit()
            print("Discord integration updated successfully!", "success")
        else:
            print("Webhook URL is required!", "danger")

    integration = DiscordIntegration.query.filter_by(service_id=process.id).first()
    return render_template('service/discord.html', service=process, integration=integration)
