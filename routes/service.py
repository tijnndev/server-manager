import shutil
import time, yaml
import subprocess
from flask import Blueprint, jsonify, redirect, request, render_template, Response, url_for, flash, session
import os, json, re
from datetime import datetime
from db import db
from models.process import Process
from models.discord_integration import DiscordIntegration
from models.git import GitIntegration
from models.subuser import SubUser
from decorators import owner_or_subuser_required, owner_required
from models.user import User
from utils import find_process_by_name, get_service_status, generate_random_string, send_email

service_routes = Blueprint('service', __name__)

SERVICES_DIRECTORY = 'active-servers'
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, 'active-servers')

def is_within_base_dir(path, base=ACTIVE_SERVERS_DIR):
    abs_base = os.path.abspath(base)
    abs_path = os.path.abspath(path)
    return os.path.commonpath([abs_base]) == os.path.commonpath([abs_base, abs_path])


from models.subuser import SubUser

def load_services():
    services = {}

    user_id = session.get('user_id')
    if not user_id:
        return services
    
    
    
    user = User.query.filter_by(id=user_id).first()

    owned_processes = Process.query.filter_by(owner_id=user_id).all()
    sub_user_processes = Process.query.join(SubUser, Process.name == SubUser.process).filter(SubUser.email == user.email).all()

    processes = owned_processes + sub_user_processes

    print(session.get('role'))
    print(user_id)
    if session.get("role") == "admin":
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


@service_routes.route('/', methods=['GET'])
def get_services():
    services = load_services()
    return jsonify(services)


@service_routes.route('/add', methods=['POST'])
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
    

@service_routes.route('/delete/<name>', methods=['POST'])
@owner_required()
def settings_delete(name):
    try:
        service = Process.query.filter_by(name=name).first()
        if not service:
            return jsonify({"error": "Service not found"}), 404
        
        git_integrations = GitIntegration.query.filter_by(process_name=name).all()
        for integration in git_integrations:
            db.session.delete(integration)

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


@service_routes.route('/start/<string:name>', methods=['POST'])
@owner_or_subuser_required()
def start_service_console(name):
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



@service_routes.route('/stop/<string:name>', methods=['POST'])
@owner_or_subuser_required()
def stop_service_console(name):
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



@service_routes.route('/console/<string:name>', methods=['GET'])
@owner_or_subuser_required()
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

@service_routes.route('/console/<name>/uptime')
@owner_or_subuser_required()
def get_console_uptime(name):
    process = find_process_by_name(name)
    if not process:
        return jsonify({'error': 'Service not found'}), 404

    try:
        service_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
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



@service_routes.route('/console/<string:name>/logs', methods=['GET'])
@owner_or_subuser_required()
def console_stream_logs(name):
    service = find_process_by_name(name)
    if not service:
        return jsonify({"error": "Service not found"}), 404

    try:
        service_dir = os.path.join(ACTIVE_SERVERS_DIR, name)

        logs_command = ['//usr/local/bin/docker-compose', 'logs', '--tail', '50']

        process = subprocess.Popen(
            logs_command,
            cwd=service_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        def generate():
            try:
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

# @service_routes.route('/console/<string:name>/send', methods=['POST'])
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

@service_routes.route('/settings/<string:name>', methods=['GET', 'POST'])
@owner_or_subuser_required()
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


@service_routes.route('/rebuild/<name>', methods=['POST'])
@owner_required()
def settings_rebuild(name):
    service = find_process_by_name(name)
    if not service:
        return redirect(url_for('service.index'))

    try:
        os.chdir(os.path.join(ACTIVE_SERVERS_DIR, name))
        os.system('//usr/local/bin/docker-compose build')

        return redirect(url_for('service.console', name=service.name))

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@service_routes.route('/discord/<string:name>', methods=['GET', 'POST'])
@owner_or_subuser_required()
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

@service_routes.route('/subusers/<string:name>', methods=['GET'])
@owner_or_subuser_required()
def subusers(name):
    service = find_process_by_name(name)
    users = SubUser.query.filter_by(process=name).all()
    return render_template('service/subusers.html', service=service, users=users)

@service_routes.route('/subusers/<string:name>/invite', methods=['GET', 'POST'])
@owner_or_subuser_required()
def invite_subuser(name):
    if request.method == 'POST':
        email = request.form.get('email')
        permissions = request.form.getlist('permissions')

        if not email or not permissions:
            flash('Please provide an email and select at least one permission.', 'danger')
            return redirect(url_for('service_routes.invite_subuser', name=name))

        existing_user = User.query.filter_by(email=email).first()

        if existing_user:
            sub_user = SubUser(
                email=existing_user.email,
                permissions=permissions,
                process=name,
                sub_role="sub_user",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.session.add(sub_user)
            db.session.commit()

            subject = "You have been added to the project"
            body = f"""
                <!DOCTYPE html>
                <html lang="en">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>You have been added to the project</title>
                    <style>
                        body {{
                            font-family: Arial, sans-serif;
                            background-color: #f4f4f4;
                            margin: 0;
                            padding: 0;
                        }}
                        .container {{
                            width: 100%;
                            max-width: 600px;
                            margin: 0 auto;
                            background-color: #ffffff;
                            padding: 20px;
                            border-radius: 8px;
                            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
                        }}
                        h1 {{
                            color: #333333;
                            font-size: 24px;
                        }}
                        p {{
                            color: #555555;
                            font-size: 16px;
                            line-height: 1.6;
                        }}
                        .button {{
                            background-color: #4CAF50;
                            color: #ffffff;
                            padding: 10px 20px;
                            text-decoration: none;
                            border-radius: 4px;
                            display: inline-block;
                        }}
                        .button:hover {{
                            background-color: #45a049;
                        }}
                        .footer {{
                            font-size: 12px;
                            color: #777777;
                            text-align: center;
                            margin-top: 20px;
                        }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h1>You have been added to the project</h1>
                        <p>Hello <strong>{existing_user.username}</strong>,</p>
                        <p>You have been successfully added as a sub-user to the project '<strong>{name}</strong>'.</p>
                        <p>You can now manage your permissions and settings from the <a href="https://yourpanel.com" class="button">project panel</a>.</p>
                        <div class="footer">
                            <p>If you have any questions, feel free to reach out to us.</p>
                            <p>&copy; 2025 ServerMonitor</p>
                        </div>
                    </div>
                </body>
                </html>
            """
            send_email(existing_user.email, subject, body, type='auth')

        else:
            reset_token = generate_random_string(10)
            new_user = User(
                username=email,
                email=email,
                password_hash="",
                reset_token=reset_token
            )
            db.session.add(new_user)
            db.session.commit()

            # Create sub-user entry for the new user
            sub_user = SubUser(
                email=email,
                permissions=permissions,
                process=name,
                sub_role="sub_user",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.session.add(sub_user)
            db.session.commit()

            subject = "Create Your Account"
            reset_url = f"https://yourapp.com/reset-password/{reset_token}"
            body = f"""
                <!DOCTYPE html>
                <html lang="en">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Create Your Account</title>
                    <style>
                        body {{
                            font-family: Arial, sans-serif;
                            background-color: #f4f4f4;
                            margin: 0;
                            padding: 0;
                        }}
                        .container {{
                            width: 100%;
                            max-width: 600px;
                            margin: 0 auto;
                            background-color: #ffffff;
                            padding: 20px;
                            border-radius: 8px;
                            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
                        }}
                        h1 {{
                            color: #333333;
                            font-size: 24px;
                        }}
                        p {{
                            color: #555555;
                            font-size: 16px;
                            line-height: 1.6;
                        }}
                        .button {{
                            background-color: #4CAF50;
                            color: #ffffff;
                            padding: 10px 20px;
                            text-decoration: none;
                            border-radius: 4px;
                            display: inline-block;
                        }}
                        .button:hover {{
                            background-color: #45a049;
                        }}
                        .footer {{
                            font-size: 12px;
                            color: #777777;
                            text-align: center;
                            margin-top: 20px;
                        }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h1>Create Your Account</h1>
                        <p>Hello,</p>
                        <p>You have been invited to create an account and join the project '<strong>{name}</strong>'.</p>
                        <p>Please <a href="https://manage.tijnn.dev{url_for("reset_token", token=reset_token)}" class="button">click here to set your password</a> and complete your registration.</p>
                        <div class="footer">
                            <p>If you have any questions, feel free to reach out to us.</p>
                            <p>&copy; 2025 ServerMonitor</p>
                        </div>
                    </div>
                </body>
                </html>
            """
            send_email(email, subject, body, type='auth')

        flash('Invitation has been sent!', 'success')
        return redirect(url_for('service.subusers', name=name))

    return redirect(url_for('service.subusers', name=name))

@service_routes.route('/subusers/<string:name>/delete/<int:user_id>', methods=['POST'])
@owner_or_subuser_required()
def delete_subuser(name, user_id):
    sub_user = SubUser.query.filter_by(id=user_id).first()
    if sub_user:
        db.session.delete(sub_user)
        db.session.commit()
        flash(f"Sub-user with email {sub_user.email} has been removed.", "success")
    else:
        flash("Sub-user not found.", "danger")
    
    return redirect(url_for('service.subusers', name=name))
