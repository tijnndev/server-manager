from collections import defaultdict
from queue import Queue
import shutil
import threading
import time, yaml
import subprocess
from flask import Blueprint, jsonify, redirect, request, render_template, Response, url_for, flash, session
import os, json, re, pytz
from datetime import datetime, UTC, timedelta
from db import db
from models.process import Process
from models.discord_integration import DiscordIntegration
from models.git import GitIntegration
from models.subuser import SubUser
from decorators import owner_or_subuser_required, owner_required
from models.user import User
from utils import find_process_by_name, find_types, get_process_status, generate_random_string, send_email, execute_handler

process_routes = Blueprint('process', __name__)

PROCESS_DIRECTORY = 'active-servers'
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, 'active-servers')


def is_within_base_dir(path, base=ACTIVE_SERVERS_DIR):
    abs_base = os.path.abspath(base)
    abs_path = os.path.abspath(path)
    return os.path.commonpath([abs_base]) == os.path.commonpath([abs_base, abs_path])


def colorize_log(log):
    ansi_escape = re.compile(r'\033\[(\d+(;\d+)*)m')
    return ansi_escape.sub(lambda match: f'<span style="color: {ansi_to_html(match.group(1))};">', log).replace('\033[0m', '</span>')


def format_timestamp(log_line):
    if not log_line.strip():
        return log_line
    
    match = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z) (.*)", log_line)
    if match:
        try:
            raw_timestamp = match.group(1)[:26]
            timestamp = datetime.strptime(raw_timestamp, "%Y-%m-%dT%H:%M:%S.%f")
            
            timestamp += timedelta(hours=2)
            
            formatted_timestamp = timestamp.strftime("[%Y-%m-%d %H:%M:%S]")
            
            return f"{formatted_timestamp} {match.group(2)}"
        except ValueError as e:
            print(e)
    else:
        match_only_timestamp = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)$", log_line.strip())
        if match_only_timestamp:
            try:
                raw_timestamp = match_only_timestamp.group(1)[:26]
                timestamp = datetime.strptime(raw_timestamp, "%Y-%m-%dT%H:%M:%S.%f")
                timestamp += timedelta(hours=2)
                return timestamp.strftime("[%Y-%m-%d %H:%M:%S]")
            except ValueError as e:
                print(e)
        else:
            return log_line
    
    return log_line


def calculate_uptime(startup_date):
    amsterdam_tz = pytz.timezone('Europe/Amsterdam')

    startup_datetime = datetime.fromisoformat(startup_date[:-1])
    startup_datetime = amsterdam_tz.localize(startup_datetime)

    current_time = datetime.now(amsterdam_tz)

    uptime = current_time - startup_datetime

    seconds = int(uptime.total_seconds())

    weeks = seconds // (7 * 24 * 3600)
    days = (seconds % (7 * 24 * 3600)) // 86400
    hours = (seconds % 86400) // 3600 - 2
    minutes = (seconds % 3600) // 60
    seconds %= 60

    uptime_str = f"{weeks}w {days}d {hours}h {minutes}m {seconds}s"

    return uptime_str.strip()


def load_process():
    process_dict = {}

    user_id = session.get('user_id')
    if not user_id:
        return process_dict
    
    user = User.query.filter_by(id=user_id).first()

    owned_processes = Process.query.filter_by(owner_id=user_id).all()
    sub_user_processes = Process.query.join(SubUser, Process.name == SubUser.process).filter(SubUser.email == user.email).all()

    processes = owned_processes + sub_user_processes

    if session.get("role") == "admin":
        processes = Process.query.all()

    for process in processes:
        response = get_process_status(process.name)

        if "error" in response:
            print(f"Error fetching status for {process.name}: {response['error']}")
        else:
            process_dict[process.name] = {
                "id": process.id,
                "type": process.type,
                "command": process.command,
                "file_location": process.file_location,
                "name": process.name,
                "status": response["status"]
            }

    return process_dict


@process_routes.route('/', methods=['GET'])
def get_process():
    processes = load_process()
    return jsonify(processes)


@process_routes.route('/create', methods=['GET', 'POST'])
def create_process():
    types = find_types()

    return render_template('create_process.html', page_title="Create Process", types=types)


@process_routes.route('/add', methods=['POST'])
def add_process():
    data = request.json

    if not data:
        return jsonify({"error": "Invalid or duplicate process name"}), 400

    process_name = data.get("name", "").strip().lower()
    process_type = data.get("type", "").strip()
    command = data.get("command", "").strip()
    dependencies = [dep.strip() for dep in data.get("dependencies", "").split(",")]

    if not process_name or process_name in load_process():
        return jsonify({"error": "Invalid or duplicate process name"}), 400

    process_dir = os.path.join(ACTIVE_SERVERS_DIR, process_name)

    if not is_within_base_dir(process_dir) or os.path.exists(process_dir):
        return jsonify({"error": "Invalid process name or directory already exists"}), 400

    try:
        os.makedirs(process_dir, exist_ok=False)

        new_process = Process(
            name=process_name,
            owner_id=session.get("user_id"),
            command=command,
            type=process_type,
            file_location=process_dir,
            dependencies=dependencies,
            id="pending",
        )

        db.session.add(new_process)
        db.session.commit()

        compose_file_path = os.path.join(process_dir, "docker-compose.yml")
        dockerfile_path = os.path.join(process_dir, "Dockerfile")

        compose_result = execute_handler(f"create.{process_type}", "create_docker_compose_file", new_process, compose_file_path)
        docker_result = execute_handler(f"create.{process_type}", "create_docker_file", new_process, dockerfile_path)

        if not compose_result.success or not docker_result.success:
            return jsonify({"error": compose_result.message if not compose_result.success else docker_result.message}), 400

        os.chdir(process_dir)
        os.system("docker-compose up -d")

        return jsonify({"redirect_url": url_for("process.console", name=new_process.name)})

    except OSError as e:
        return jsonify({"error": f"Failed to create process directory: {e}"}), 500


@process_routes.route('/delete/<name>', methods=['POST'])
@owner_required()
def settings_delete(name):
    try:
        process = Process.query.filter_by(name=name).first()
        if not process:
            return jsonify({"error": "Process not found"}), 404
        
        git_integrations = GitIntegration.query.filter_by(process_name=name).all()
        for integration in git_integrations:
            db.session.delete(integration)

        process_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
        if os.path.exists(process_dir):
            try:
                os.chdir(process_dir)
                subprocess.run(['docker-compose', 'down'], check=True)
                print(f"Process {name} stopped and removed successfully via docker-compose")
            except subprocess.CalledProcessError as e:
                print(f"Error stopping process {name}: {e}")

            shutil.rmtree(process_dir)
            print(f"Process directory {process_dir} removed successfully")

        db.session.delete(process)
        db.session.commit()

        return redirect('/')

    except Exception as e:
        print(f"Error deleting process: {e}")
        return jsonify({"error": str(e)}), 500


@process_routes.route('/start/<string:name>', methods=['POST'])
@owner_or_subuser_required()
def start_process_console(name):
    process = find_process_by_name(name)
    if not process:
        return jsonify({"error": "Process not found"}), 404

    try:
        os.chdir(os.path.join(ACTIVE_SERVERS_DIR, name))
        
        subprocess.run(['docker-compose', 'up', '-d'], check=True)

        time.sleep(2)

        return jsonify({"message": f"Process {name} started successfully.", "status": get_process_status(process.name), "ok": True})

    except subprocess.CalledProcessError as e:
        error_message = e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)
        return jsonify({"error": error_message, "ok": False}), 500
    except Exception as e:
        error_message = str(e)
        return jsonify({"error": error_message, "ok": False}), 500


@process_routes.route('/stop/<string:name>', methods=['POST'])
@owner_or_subuser_required()
def stop_process_console(name):
    process = find_process_by_name(name)
    if not process:
        return jsonify({"error": "Process not found"}), 404

    try:
        os.chdir(os.path.join(ACTIVE_SERVERS_DIR, name))
        os.system('docker-compose stop')

        return jsonify({"message": f"Process {name} stopped successfully."})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@process_routes.route('/console/<string:name>', methods=['GET'])
@owner_or_subuser_required()
def console(name):
    process = find_process_by_name(name)
    
    if not process:
        return jsonify({"error": "Process not found"}), 404
    
    response = get_process_status(process.name)

    try:
        status = response["status"]
    except KeyError:
        status = "Failed"
    return render_template('process/console.html', page_title="Console", process=process, process_status=status)


@process_routes.route('/console/<name>/uptime')
@owner_or_subuser_required()
def get_console_uptime(name):
    process = find_process_by_name(name)
    if not process:
        return jsonify({'error': 'Process not found'}), 404

    try:
        process_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
        os.chdir(process_dir)

        result = subprocess.run(['docker-compose', 'ps', '-q'], capture_output=True, text=True, check=True)
        container_id = result.stdout.strip()

        if not container_id:
            return jsonify({'uptime': '0w 0d 0h 0m 0s', 'error': 'Process is not running.'})

        result = subprocess.run(['docker', 'inspect', '--format', '{{.State.StartedAt}}', container_id],
                                capture_output=True, text=True, check=True)
        startup_date = result.stdout.strip()

        uptime = calculate_uptime(startup_date)
        return jsonify({'uptime': uptime})

    except subprocess.CalledProcessError as e:
        return jsonify({'uptime': '0w 0d 0h 0m 0s', 'error': f"Failed to get process status: {e.stderr}"})
    except Exception as e:
        return jsonify({'uptime': '0w 0d 0h 0m 0s', 'error': str(e)})
    

live_log_streams = defaultdict(Queue)


@process_routes.route('/console/<string:name>/logs', methods=['GET'])
@owner_or_subuser_required()
def console_stream_logs(name):
    process = find_process_by_name(name)
    if not process:
        return jsonify({"error": "Process not found"}), 404

    process_dir = os.path.join(ACTIVE_SERVERS_DIR, name)

    logs_command = ['docker-compose', 'logs', '--tail', '50', '--timestamps', '--no-log-prefix']
    docker_logs = subprocess.Popen(
        logs_command,
        cwd=process_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    def generate():
        try:
            if docker_logs.stdout is not None:
                for line in iter(docker_logs.stdout.readline, ''):
                    yield f"data: {colorize_log(format_timestamp(line.strip()))}\n\n"

            while True:
                try:
                    line = live_log_streams[name].get(timeout=1)
                    yield f"data: {line}\n\n"
                except:
                    if docker_logs.poll() is not None:
                        break

        except Exception as e:
            yield f"data: [stream error] {str(e)}\n\n"
        finally:
            docker_logs.terminate()
            docker_logs.wait()

    return Response(generate(), content_type='text/event-stream')



# @process_routes.route('/console/<string:name>/send', methods=['POST'])
# def send_command(name):
#     process = find_process_by_name(name)
#     if not process or not request.json:
#         return jsonify({"error": "Process not found"}), 404

#     command = request.json.get('command')
#     if not command:
#         return jsonify({"error": "No command provided"}), 400

#     try:
#         container = client.containers.get(process.id)
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
        '0': 'white',
        "38;5;214": "orange",
        "38;5;226": "yellow",
        "38;5;196": "red",
    }
    return color_map.get(ansi_code, "white")


@process_routes.route('/settings/<string:name>', methods=['GET', 'POST'])
@owner_or_subuser_required()
def settings(name):
    process = find_process_by_name(name)
    types = find_types()

    if not process:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        old_name = process.name
        new_name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        command = request.form.get('command', '').strip()
        type_ = request.form.get('type', '').strip()
        params = request.form.get('params', '').strip()

        if not command:
            return "Process command is required", 400

        old_dir = os.path.join(ACTIVE_SERVERS_DIR, old_name)
        new_dir = os.path.join(ACTIVE_SERVERS_DIR, new_name)

        if old_name != new_name:
            if os.path.exists(new_dir):
                return f"Directory '{new_name}' already exists", 400
            if os.path.exists(old_dir):
                try:
                    os.rename(old_dir, new_dir)
                except OSError as e:
                    return f"Failed to rename directory: {str(e)}", 500

        compose_path = os.path.join(new_dir, 'docker-compose.yml')
        dockerfile_path = os.path.join(new_dir, 'Dockerfile')

        if not update_compose_file(compose_path, new_name, command):
            return f"Failed to update docker-compose.yml for '{new_name}'", 404

        if os.path.exists(dockerfile_path):
            update_dockerfile(dockerfile_path, command)

        process.name = new_name
        process.description = description
        process.command = command
        process.type = type_
        process.params = params

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return f"Database commit failed: {str(e)}", 500

        return redirect(url_for('process.console', name=new_name))

    return render_template('process/settings.html', page_title="Settings", process=process, types=types)


def update_compose_file(compose_path, process_name, command):
    """Update docker-compose.yml with the new command."""
    if not os.path.exists(compose_path):
        return False

    with open(compose_path) as compose_file:
        compose_data = yaml.safe_load(compose_file)

    if process_name not in compose_data.get('services', {}):
        return False

    compose_data['services'][process_name]['command'] = command.split()

    with open(compose_path, 'w') as compose_file:
        yaml.safe_dump(compose_data, compose_file, default_flow_style=False)

    print(f"docker-compose.yml for {process_name} updated with new command: {command}")
    return True


def update_dockerfile(dockerfile_path, command):
    """Update CMD/ENTRYPOINT in the Dockerfile."""
    with open(dockerfile_path) as dockerfile:
        lines = dockerfile.readlines()

    for idx, line in enumerate(lines):
        if line.startswith(("CMD", "ENTRYPOINT")):
            lines[idx] = 'CMD [{}]\n'.format(", ".join(f'"{word}"' for word in command.split()))
            break
    else:
        lines.append(f'CMD {command.split()}\n')

    with open(dockerfile_path, 'w') as dockerfile:
        dockerfile.writelines(lines)

    print(f"Dockerfile for {dockerfile_path} updated with new command: {command}")


def rebuild_process(project_dir, name):
    try:
        subprocess.run(['docker-compose', 'down'], cwd=project_dir, check=True)

        process = subprocess.Popen(
            ['docker-compose', 'build'],
            cwd=project_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        if process.stdout is not None:
            with process.stdout:
                for line in iter(process.stdout.readline, ''):
                    formatted = format_timestamp(line.strip())
                    colored = colorize_log(formatted)
                    print(colored)
                    live_log_streams[name].put(colored)

        process.wait()
        live_log_streams[name].put('[rebuild] Build process finished.')

    except Exception as e:
        live_log_streams[name].put(f'[rebuild error] {str(e)}')



@process_routes.route('/rebuild/<name>', methods=['POST'])
@owner_required()
def settings_rebuild(name):
    process = find_process_by_name(name)
    if not process:
        return redirect(url_for('process.index'))

    project_dir = os.path.join(ACTIVE_SERVERS_DIR, name)

    if not os.path.isdir(project_dir):
        return jsonify({"error": "Project directory not found"}), 404

    threading.Thread(target=rebuild_process, args=(project_dir, process.name)).start()

    return redirect(url_for('process.console', name=process.name))


@process_routes.route('/discord/<string:name>', methods=['GET', 'POST'])
@owner_or_subuser_required()
def discord(name):
    process = find_process_by_name(name)
    if request.method == 'POST':
        webhook_url = request.form.get('webhook_url')
        events = request.form.getlist('events')

        if webhook_url:
            integration = DiscordIntegration.query.filter_by(process_name=process.name).first()
            if not integration:
                integration = DiscordIntegration(process_name=process.name, webhook_url=webhook_url, events=json.dumps(events))
            else:
                integration.webhook_url = webhook_url
                integration.events_list = events

            db.session.add(integration)
            db.session.commit()
            print("Discord integration updated successfully!", "success")
        else:
            print("Webhook URL is required!", "danger")

    integration = DiscordIntegration.query.filter_by(process_name=process.name).first()
    return render_template('process/discord.html', page_title="Discord", process=process, integration=integration)


@process_routes.route('/subusers/<string:name>', methods=['GET'])
@owner_or_subuser_required()
def subusers(name):
    process = find_process_by_name(name)
    users = SubUser.query.filter_by(process=name).all()
    return render_template('process/subusers.html', page_title="Sub Users", process=process, users=users)


@process_routes.route('/subusers/<string:name>/invite', methods=['GET', 'POST'])
@owner_or_subuser_required()
def invite_subuser(name):
    if request.method == 'POST':
        email = request.form.get('email')
        permissions = request.form.getlist('permissions')

        if not email or not permissions:
            flash('Please provide an email and select at least one permission.', 'danger')
            return redirect(url_for('process_routes.invite_subuser', name=name))

        existing_user = User.query.filter_by(email=email).first()

        if existing_user:
            sub_user = SubUser(
                email=existing_user.email,
                permissions=permissions,
                process=name,
                sub_role="sub_user",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC)
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
                        <p>You can now manage your permissions and settings from the <a href="https://manage.tijnn.dev" class="button">project panel</a>.</p>
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

            sub_user = SubUser(
                email=email,
                permissions=permissions,
                process=name,
                sub_role="sub_user",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC)
            )
            db.session.add(sub_user)
            db.session.commit()

            subject = "Create Your Account"
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
                        <p>Please <a href="https://manage.tijnn.dev{url_for("auth.reset_token", token=reset_token)}" class="button">click here to set your password</a> and complete your registration.</p>
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
        return redirect(url_for('process.subusers', name=name))

    return redirect(url_for('process.subusers', name=name))


@process_routes.route('/subusers/<string:name>/delete/<int:user_id>', methods=['POST'])
@owner_or_subuser_required()
def delete_subuser(name, user_id):
    sub_user = SubUser.query.filter_by(id=user_id).first()
    if sub_user:
        db.session.delete(sub_user)
        db.session.commit()
        flash(f"Sub-user with email {sub_user.email} has been removed.", "success")
    else:
        flash("Sub-user not found.", "danger")
    
    return redirect(url_for('process.subusers', name=name))


@process_routes.route('/schedule/<string:name>', methods=['GET', 'POST'])
@owner_or_subuser_required()
def schedule(name):
    process = find_process_by_name(name)
    if not process:
        return jsonify({"error": "Process not found"}), 404

    cron_jobs = []

    if request.method == 'POST':
        data = request.form
        if not data or 'action' not in data or 'schedule' not in data:
            return jsonify({"error": "Invalid request data"}), 400

        action = data['action']
        schedule = data['schedule']

        if action not in {'start', 'stop'}:
            return jsonify({"error": "Invalid action. Use 'start' or 'stop'."}), 400

        cron_command = f"echo '{schedule} root docker-compose -f {os.path.join(ACTIVE_SERVERS_DIR, name, 'docker-compose.yml')} {action}' | sudo tee -a /etc/cron.d/{name.replace('.', '_')}_power_event"

        try:
            subprocess.run(cron_command, shell=True, check=True)
        except subprocess.CalledProcessError as e:
            return jsonify({"error": f"Failed to schedule event: {str(e)}"}), 500

    cron_jobs = get_current_cron_jobs(name)
    return render_template('process/schedule.html', page_title="Schedule", process=process, cron_jobs=cron_jobs)


def get_current_cron_jobs(process_name):
    """
    Get the current cron jobs for a specific process.
    This will list all cron jobs related to the process's name in /etc/cron.d.
    """
    cron_jobs = []
    try:  # noqa: PLR1702
        print(process_name.replace(".", "_"))
        cron_file_path = os.path.join('/etc/cron.d', f'{process_name.replace(".", "_")}_power_event')

        if os.path.exists(cron_file_path):
            with open(cron_file_path) as cron_file:
                lines = cron_file.readlines()
                for line in lines:
                    if line.strip() and not line.startswith('#'):
                        parts = line.split()
                        if len(parts) >= 6:
                            cron_jobs.append({
                                "name": process_name,
                                "schedule": " ".join(parts[:5]),
                                "command": " ".join(parts[5:]),
                                "line": line
                            })
        return cron_jobs
    except Exception as e:
        return {"error": str(e)}


@process_routes.route('/schedule/<string:name>/delete', methods=['POST'])
@owner_or_subuser_required()
def delete_cron_job(name):
    """
    This route handles the deletion of a specific cron job related to a process.
    """
    process = find_process_by_name(name)
    if not process:
        return jsonify({"error": "Process not found"}), 404

    data = request.form
    if 'line' not in data:
        return jsonify({"error": "Missing line parameter"}), 400

    schedule_to_remove = data['line'].strip()
    cron_file_path = os.path.join('/etc/cron.d', f'{name.replace(".", "_")}_power_event')

    try:
        with open(cron_file_path) as cron_file:
            lines = cron_file.readlines()

        with open(cron_file_path, 'w') as cron_file:
            for line in lines:
                print(schedule_to_remove)
                print(line.strip() != schedule_to_remove)
                if line.strip() != schedule_to_remove:
                    cron_file.write(line)

        return redirect(url_for('process.schedule', name=process.name))
    except FileNotFoundError as e:
        return jsonify({"error": f"Failed to remove cron job: {str(e)}"}), 500
    except PermissionError as e:
        return jsonify({"error": f"Failed to remove cron job: {str(e)}"}), 500
