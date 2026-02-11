from collections import defaultdict
from queue import Queue
import shutil
import threading
import time, yaml
import subprocess
from flask import stream_with_context
from flask import Blueprint, jsonify, redirect, request, render_template, Response, url_for, flash, session
import os, json, re, pytz
import shlex
import sys
from datetime import datetime, UTC, timedelta
from db import db
from models.process import Process
from models.git import GitIntegration
from models.subuser import SubUser
from models.activity_log import ActivityLog
from decorators import owner_or_subuser_required, owner_required
from models.user import User
from utils import find_process_by_name, find_types, get_process_status, generate_random_string, send_email, execute_handler, is_always_running_container, start_process_in_container, stop_process_in_container, execute_command_in_container, execute_interactive_command_in_container, get_server_ip
from utils.cloudflare import extract_zone_name, get_zone_id, create_dns_record, find_dns_record, delete_dns_record
from models.user_settings import UserSettings
from utils.discord import DiscordNotifier, get_user_discord_settings

process_routes = Blueprint('process', __name__)

PROCESS_DIRECTORY = 'active-servers'
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, 'active-servers')

# Lightweight in-memory cache to avoid repeated docker status calls during rapid page loads
PROCESS_STATUS_CACHE = {}
PROCESS_STATUS_CACHE_TTL = 5  # seconds


def _make_process_cache_key(user_id, role):
    return f"{role or 'user'}:{user_id or 'anon'}"


def invalidate_process_cache(cache_key=None):
    """Invalidate cached process status results."""
    if cache_key:
        PROCESS_STATUS_CACHE.pop(cache_key, None)
    else:
        PROCESS_STATUS_CACHE.clear()


def get_container_id(process_name):
    process_dir = os.path.join(ACTIVE_SERVERS_DIR, process_name)
    try:
        result = subprocess.run(
            ['docker-compose', 'ps', '-q', process_name],
            capture_output=True,
            text=True,
            check=True,
            cwd=process_dir
        )
        container_id = result.stdout.strip()
        return container_id or None
    except subprocess.CalledProcessError as e:
        print(f"[container_id] Failed to get container ID for {process_name}: {e.stderr}")
    except FileNotFoundError:
        print(f"[container_id] Directory not found for {process_name}")
    return None


def get_main_command_for_container(container_id, fallback_command=""):
    try:
        result = subprocess.run(
            ['docker', 'inspect', '--format', '{{range .Config.Env}}{{println .}}{{end}}', container_id],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith('MAIN_COMMAND='):
                    return line.split('=', 1)[1].strip('"')
    except Exception as e:
        print(f"[main_command] Failed to inspect container {container_id}: {e}")
    return fallback_command


def get_process_pid_in_container(container_id, command):
    if not container_id or not command:
        return None

    search_expr = shlex.quote(command)
    shell_cmd = (
        f"ps -eo pid,args | grep -F {search_expr} | grep -v grep | "
        "awk '{print $1}' | head -n 1"
    )

    try:
        result = subprocess.run(
            ['docker', 'exec', container_id, 'sh', '-c', shell_cmd],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            pid = result.stdout.strip()
            return int(pid) if pid.isdigit() else None
    except Exception as e:
        print(f"[process_pid] Failed to obtain PID for container {container_id}: {e}")
    return None


def update_process_runtime_metadata(process):
    container_id = get_container_id(process.name)
    if container_id:
        process.id = container_id
        main_command = get_main_command_for_container(container_id, process.command)
        process.process_pid = get_process_pid_in_container(container_id, main_command)
    else:
        process.process_pid = None

    try:
        db.session.add(process)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[process_metadata] Failed to update metadata for {process.name}: {e}")


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

    cache_key = _make_process_cache_key(user_id, session.get("role"))
    now = time.time()
    cached_entry = PROCESS_STATUS_CACHE.get(cache_key)
    if cached_entry and now - cached_entry.get("timestamp", 0) < PROCESS_STATUS_CACHE_TTL:
        # Return a shallow copy to avoid accidental mutation of cached data
        return dict(cached_entry.get("data", {}))
    
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
            status = "Unknown"
        else:
            # Extract status from response
            status = response.get("status", "Unknown")
            
            # Map "Container Not Running" to "Exited" for cleaner display
            if status == "Container Not Running":
                status = "Exited"
                
            process_dict[process.name] = {
                "id": process.id,
                "type": process.type,
                "command": process.command,
                "file_location": process.file_location,
                "name": process.name,
                "status": status,
                "created_at": process.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }

    PROCESS_STATUS_CACHE[cache_key] = {"timestamp": now, "data": process_dict}
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
        subprocess.run(['docker-compose', 'up', '-d'], check=True)

        update_process_runtime_metadata(new_process)

        # Log activity
        try:
            ActivityLog.log_activity(
                user_id=session.get('user_id'),
                username=session.get('username'),
                action='created_process',
                target=new_process.name,
                details=f"Type: {process_type}",
                request_obj=request
            )
        except Exception as log_error:
            print(f"Failed to log activity: {log_error}")

        return jsonify({"redirect_url": url_for("process.console", name=new_process.name)})

    except OSError as e:
        return jsonify({"error": f"Failed to create process directory: {e}"}), 500
    except subprocess.CalledProcessError as e:
        return jsonify({"error": f"Failed to start docker container: {e}"}), 500


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

        # Log activity
        try:
            ActivityLog.log_activity(
                user_id=session.get('user_id'),
                username=session.get('username'),
                action='deleted_process',
                target=name,
                details=f"Process deleted and container removed",
                request_obj=request
            )
        except Exception as log_error:
            print(f"Failed to log activity: {log_error}")

        return redirect('/')

    except Exception as e:
        print(f"Error deleting process: {e}")
        return jsonify({"error": str(e)}), 500


@process_routes.route('/start/<string:name>', methods=['POST'])
@owner_or_subuser_required()
def start_process_console(name):
    process = find_process_by_name(name)
    if not process:
        return jsonify({
            "error": f"Process '{name}' not found. It may have been deleted or never existed.",
            "ok": False
        }), 404

    try:
        # Check if this is an always-running container
        if is_always_running_container(name):
            # Use process-level control
            result = start_process_in_container(name)
            if result["success"]:
                update_process_runtime_metadata(process)
                invalidate_process_cache()
                return jsonify({
                    "message": result["message"], 
                    "status": get_process_status(process.name), 
                    "ok": True
                })
            else:
                return jsonify({
                    "error": f"Failed to start process: {result['error']}. Check if the container is properly configured.",
                    "ok": False
                }), 500
        else:
            # Use traditional container-level control
            process_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
            
            if not os.path.exists(process_dir):
                return jsonify({
                    "error": f"Process directory not found: {process_dir}. The process files may have been deleted.",
                    "ok": False
                }), 404
            
            if not os.path.exists(os.path.join(process_dir, 'docker-compose.yml')):
                return jsonify({
                    "error": f"docker-compose.yml not found for process '{name}'. Recreate the process or check its configuration.",
                    "ok": False
                }), 404
            
            os.chdir(process_dir)
            
            subprocess.run(['docker-compose', 'up', '-d'], check=True, capture_output=True, text=True)

            time.sleep(2)

            update_process_runtime_metadata(process)
            invalidate_process_cache()

            # Log activity
            try:
                ActivityLog.log_activity(
                    user_id=session.get('user_id'),
                    username=session.get('username'),
                    action='started_process',
                    target=name,
                    details="Process started successfully",
                    request_obj=request
                )
            except Exception as log_error:
                print(f"Failed to log activity: {log_error}")

            # Send Discord notification
            try:
                from utils.discord import get_user_discord_settings, DiscordNotifier
                discord_settings = get_user_discord_settings(process.owner_id)
                if discord_settings and discord_settings.get('notify_power_actions'):
                    user = User.query.get(process.owner_id)
                    DiscordNotifier.notify_power_action(
                        webhook_url=discord_settings['webhook_url'],
                        action='started',
                        process_name=process.name,
                        process_type=process.type,
                        user=user.username if user else 'Unknown',
                        success=True
                    )
            except Exception as discord_error:
                print(f"Failed to send Discord notification: {discord_error}")

            return jsonify({
                "message": f"Process '{name}' started successfully.", 
                "status": get_process_status(process.name), 
                "ok": True
            })

    except subprocess.CalledProcessError as e:
        error_details = e.stderr if e.stderr else str(e)
        return jsonify({
            "error": f"Docker error starting '{name}': {error_details}. Ensure Docker is running and docker-compose.yml is valid.",
            "ok": False
        }), 500
    except FileNotFoundError:
        return jsonify({
            "error": f"Docker or docker-compose not found. Install Docker and ensure it's in your PATH.",
            "ok": False
        }), 500
    except PermissionError:
        return jsonify({
            "error": f"Permission denied starting '{name}'. Run the server with appropriate Docker permissions.",
            "ok": False
        }), 403
    except Exception as e:
        return jsonify({
            "error": f"Unexpected error starting '{name}': {str(e)}. Check the console logs for details.",
            "ok": False
        }), 500


@process_routes.route('/stop/<string:name>', methods=['POST'])
@owner_or_subuser_required()
def stop_process_console(name):
    process = find_process_by_name(name)
    if not process:
        return jsonify({"error": "Process not found"}), 404

    try:
        # Check if this is an always-running container
        if is_always_running_container(name):
            # Use process-level control
            result = stop_process_in_container(name)
            if result["success"]:
                process.process_pid = None
                try:
                    db.session.add(process)
                    db.session.commit()
                except Exception as db_err:
                    db.session.rollback()
                    print(f"[process_metadata] Failed to clear PID for {name}: {db_err}")
                return jsonify({"message": result["message"]})
            else:
                return jsonify({"error": result["error"]}), 500
        else:
            # Use traditional container-level control
            os.chdir(os.path.join(ACTIVE_SERVERS_DIR, name))
            os.system('docker-compose stop')

            process.process_pid = None
            try:
                db.session.add(process)
                db.session.commit()
            except Exception as db_err:
                db.session.rollback()
                print(f"[process_metadata] Failed to clear PID for {name}: {db_err}")

            # Log activity
            try:
                ActivityLog.log_activity(
                    user_id=session.get('user_id'),
                    username=session.get('username'),
                    action='stopped_process',
                    target=name,
                    details="Process stopped successfully",
                    request_obj=request
                )
            except Exception as log_error:
                print(f"Failed to log activity: {log_error}")

            invalidate_process_cache()

            # Send Discord notification
            try:
                from utils.discord import get_user_discord_settings, DiscordNotifier
                discord_settings = get_user_discord_settings(process.owner_id)
                if discord_settings and discord_settings.get('notify_power_actions'):
                    user = User.query.get(process.owner_id)
                    DiscordNotifier.notify_power_action(
                        webhook_url=discord_settings['webhook_url'],
                        action='stopped',
                        process_name=process.name,
                        process_type=process.type,
                        user=user.username if user else 'Unknown',
                        success=True
                    )
            except Exception as discord_error:
                print(f"Failed to send Discord notification: {discord_error}")

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

    def generate():
        try:
            # Check if this is an always-running container
            is_always_running = is_always_running_container(name)
            
            if is_always_running:
                # For always-running containers, stream both container logs and process logs
                container_id = None
                try:
                    result = subprocess.run(['docker-compose', 'ps', '-q', name], 
                                          capture_output=True, text=True, check=True, cwd=process_dir)
                    container_id = result.stdout.strip()
                except Exception:
                    print("[DEBUG] Failed to get container ID")
                
                # Stream existing container logs first (last 20 lines)
                if container_id:
                    try:
                        container_logs = subprocess.run(['docker-compose', 'logs', '--tail', '150', '--timestamps', '--no-log-prefix'], 
                                                      capture_output=True, text=True, cwd=process_dir)
                        if container_logs.stdout:
                            for line in container_logs.stdout.split('\n'):
                                if line.strip():
                                    yield f"data: {colorize_log(format_timestamp(line.strip()))}\n\n"
                    except Exception as e:
                        print(f"[DEBUG] Error getting container logs: {e}")
                
                # Stream existing process logs from log file (if exists)
                if container_id:
                    log_file = f"/tmp/{name}_process.log"
                    try:
                        log_result = subprocess.run(['docker', 'exec', container_id, 'tail', '-150', log_file], 
                                                  capture_output=True, text=True)
                        if log_result.returncode == 0 and log_result.stdout:
                            for line in log_result.stdout.split('\n'):
                                if line.strip():
                                    log_line = f"{colorize_log(line.strip())}"
                                    print(log_line)
                                    yield f"data: {log_line}\n\n"
                    except Exception as e:
                        print(f"[DEBUG] Error getting process logs: {e}")
                
                # Start continuous streaming of process logs in background
                log_streaming_process = None
                if container_id:
                    try:
                        log_file = f"/tmp/{name}_process.log"
                        log_streaming_process = subprocess.Popen(
                            ['docker', 'exec', container_id, 'tail', '-n', '150', '-f', log_file],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            bufsize=1
                        )
                        print(f"[DEBUG] Started log streaming process for {name}")
                    except Exception as e:
                        print(f"[DEBUG] Failed to start log streaming: {e}")
                
                # Stream live logs using a simpler approach that works on Windows
                last_log_position = 0
                heartbeat_counter = 0
                no_data_counter = 0
                
                while True:
                    try:
                        has_data = False
                        
                        # Stream from live log queue (this handles manual messages)
                        try:
                            line = live_log_streams[name].get(timeout=0.1)
                            yield f"data: {colorize_log(line)}\n\n"
                            has_data = True
                            no_data_counter = 0
                            continue
                        except Exception:
                            pass  # Timeout, continue to other sources
                        
                        # Get new logs from process log file (Windows-compatible approach)
                        if container_id:
                            try:
                                log_file = f"/tmp/{name}_process.log"
                                # Get file size first
                                size_result = subprocess.run(['docker', 'exec', container_id, 'wc', '-c', log_file], 
                                                           capture_output=True, text=True, timeout=2)
                                if size_result.returncode == 0:
                                    current_size = int(size_result.stdout.strip().split()[0])
                                    if current_size > last_log_position:
                                        # Get new content since last position
                                        tail_result = subprocess.run(
                                            ['docker', 'exec', container_id, 'tail', '-n', '150', log_file], 
                                            capture_output=True, text=True, timeout=2
                                        )
                                        if tail_result.returncode == 0 and tail_result.stdout:
                                            for line in tail_result.stdout.split('\n'):
                                                if line.strip():
                                                    yield f"data: {colorize_log(line.strip())}\n\n"
                                                    has_data = True
                                        last_log_position = current_size
                                        no_data_counter = 0
                            except subprocess.TimeoutExpired:
                                pass  # Timeout, continue
                            except Exception as e:
                                print(f"[DEBUG] Error getting new logs: {e}")
                        
                        # Send heartbeat/keep-alive comment every 15 seconds
                        # Comments in SSE don't trigger the onmessage event
                        heartbeat_counter += 1
                        if heartbeat_counter >= 150:  # 150 * 0.1s = 15 seconds
                            yield ": keepalive\n\n"  # SSE comment for keepalive
                            heartbeat_counter = 0
                        
                        # Track if no data is being received
                        if not has_data:
                            no_data_counter += 1
                        
                        # Small delay to prevent excessive polling
                        import time
                        time.sleep(0.1)
                        
                    except GeneratorExit:
                        break
                    except Exception as e:
                        print(f"[DEBUG] Stream error: {str(e)}")
                        break
                
                # Cleanup
                if log_streaming_process:
                    try:
                        log_streaming_process.terminate()
                        log_streaming_process.wait(timeout=5)
                    except Exception:
                        try:
                            log_streaming_process.kill()
                        except Exception:
                            pass
            
            else:
                # Traditional container log streaming (existing behavior)
                logs_command = ['docker-compose', 'logs', '--tail', '50', '--timestamps', '--no-log-prefix']
                docker_logs = subprocess.Popen(
                    logs_command,
                    cwd=process_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1
                )

                if docker_logs.stdout is not None:
                    for line in iter(docker_logs.stdout.readline, ''):
                        yield f"data: {colorize_log(format_timestamp(line.strip()))}\n\n"

                while True:
                    try:
                        line = live_log_streams[name].get(timeout=1)
                        yield f"data: {line}\n\n"
                    except Exception:
                        if docker_logs.poll() is not None:
                            break

                docker_logs.terminate()
                docker_logs.wait()

        except Exception as e:
            yield f"data: [stream error] {str(e)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"  # for Nginx
        }
    )


@process_routes.route('/execute/<string:name>', methods=['POST'])
@owner_or_subuser_required()
def execute_command(name):
    """Execute a command inside the container"""
    process = find_process_by_name(name)
    if not process:
        return jsonify({
            "success": False,
            "error": f"Process '{name}' not found. Ensure the process exists and is running."
        }), 404

    try:
        data = request.get_json()
        if not data or 'command' not in data:
            return jsonify({
                "success": False,
                "error": "No command provided. Please enter a command to execute."
            }), 400

        command = data.get('command', '').strip()
        working_dir = data.get('working_dir', '/app')
        timeout = data.get('timeout', 30)

        if not command:
            return jsonify({
                "success": False,
                "error": "Command cannot be empty. Please enter a valid command."
            }), 400

        # Validate timeout
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            return jsonify({
                "success": False,
                "error": "Invalid timeout value. Must be a positive number."
            }), 400

        # Execute the command
        result = execute_command_in_container(name, command, working_dir, timeout)
        
        # Add command and result to live log stream for real-time viewing
        
    # ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        # live_log_streams[name].put(f'[{ts}] $ {command}')
        
        if result['success']:
            # Add output to live stream
            if result.get('stdout'):
                for line in result['stdout'].split('\n'):
                    if line.strip():
                        ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
                        live_log_streams[name].put(f"[{ts}] {line}")
            if result.get('stderr'):
                for line in result['stderr'].split('\n'):
                    if line.strip():
                        ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
                        live_log_streams[name].put(f'[{ts}] [ERROR] {line}')
        else:
            ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
            error_msg = result.get("error", "Command failed")
            live_log_streams[name].put(f'[{ts}] [ERROR] {error_msg}')
            
            # Enhance error message
            if "container not running" in error_msg.lower():
                result["error"] = f"Cannot execute command: Container is not running. Start the process first."
            elif "timeout" in error_msg.lower():
                result["error"] = f"Command timed out after {timeout}s. Try increasing the timeout or check if the command is stuck."
            elif "permission denied" in error_msg.lower():
                result["error"] = f"Permission denied: {error_msg}. The container user may lack necessary permissions."
        
        return jsonify(result)

    except ValueError as e:
        error_message = f"Invalid input: {str(e)}"
        print(f"[DEBUG] ValueError in execute_command route: {error_message}")
        return jsonify({"success": False, "error": error_message}), 400
    except TimeoutError:
        error_message = f"Command execution timed out after {timeout}s. The command may be hanging or taking too long."
        print(f"[DEBUG] TimeoutError in execute_command route: {error_message}")
        return jsonify({"success": False, "error": error_message}), 504
    except Exception as e:
        error_message = f"Unexpected error executing command: {str(e)}. Check container logs for details."
        print(f"[DEBUG] Exception in execute_command route: {error_message}")
        return jsonify({"success": False, "error": error_message}), 500


@process_routes.route('/execute/<string:name>/interactive', methods=['POST'])
@owner_or_subuser_required()
def start_interactive_command(name):
    """Start an interactive command inside the container"""
    process = find_process_by_name(name)
    if not process:
        return jsonify({"error": "Process not found"}), 404

    try:
        data = request.get_json()
        if not data or 'command' not in data:
            return jsonify({"error": "Command is required"}), 400

        command = data.get('command', '').strip()
        working_dir = data.get('working_dir', '/app')

        if not command:
            return jsonify({"error": "Command cannot be empty"}), 400

        # Start the interactive command
        result = execute_interactive_command_in_container(name, command, working_dir)
        
        # Add command start notification to live log stream
        live_log_streams[name].put(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] Starting interactive: {command}')
        
        if result['success']:
            # Store process reference for potential future interaction
            # Note: In a real implementation, you'd want to store this in a session or database
            # for tracking active interactive sessions
            live_log_streams[name].put(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] Interactive command started (PID: {result["process"].pid})')
            return jsonify({
                "success": True,
                "message": result["message"],
                "process_pid": result["process"].pid
            })
        else:
            live_log_streams[name].put(f'[ERROR] Failed to start interactive command: {result.get("error")}')
            return jsonify(result)

    except Exception as e:
        error_message = str(e)
        return jsonify({"success": False, "error": error_message}), 500


@process_routes.route('/execute/<string:name>/shell', methods=['POST'])
@owner_or_subuser_required()
def open_shell(name):
    """Open a shell session inside the container"""
    process = find_process_by_name(name)
    if not process:
        return jsonify({"error": "Process not found"}), 404

    try:
        data = request.get_json() or {}
        working_dir = data.get('working_dir', '/app')
        shell = data.get('shell', '/bin/bash')

        # Try bash first, fallback to sh if bash doesn't exist
        shell_command = f"cd {working_dir} && if command -v {shell} >/dev/null 2>&1; then exec {shell}; else exec /bin/sh; fi"
        
        # Start the interactive shell
        result = execute_interactive_command_in_container(name, shell_command, working_dir)
        
        # Add shell start notification to live log stream
        live_log_streams[name].put(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] Opening shell session')
        
        if result['success']:
            live_log_streams[name].put(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] Shell session started (PID: {result["process"].pid})')
            return jsonify({
                "success": True,
                "message": "Shell session started",
                "process_pid": result["process"].pid,
                "working_dir": working_dir,
                "shell": shell
            })
        else:
            live_log_streams[name].put(f'[ERROR] Failed to start shell: {result.get("error")}')
            return jsonify(result)

    except Exception as e:
        error_message = str(e)
        return jsonify({"success": False, "error": error_message}), 500


@process_routes.route('/clear-logs/<string:name>', methods=['POST'])
@owner_or_subuser_required()
def clear_logs(name):
    """Clear the persistent log file for a process"""
    process = find_process_by_name(name)
    if not process:
        return jsonify({"error": "Process not found"}), 404

    try:
        process_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
        os.chdir(process_dir)

        # Get container ID
        result = subprocess.run(['docker-compose', 'ps', '-q', name], capture_output=True, text=True, check=True)
        container_id = result.stdout.strip()

        if not container_id:
            return jsonify({"error": "Container is not running"}), 400

        # Clear the log file
        log_file = f"/tmp/{name}_process.log"
        result = subprocess.run(['docker', 'exec', container_id, 'sh', '-c', f'> {log_file}'], 
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            # Add notification to live stream
            live_log_streams[name].put(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] ===== LOGS CLEARED =====')
            return jsonify({"success": True, "message": "Logs cleared successfully"})
        else:
            return jsonify({"success": False, "error": "Failed to clear logs"}), 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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
        domain = request.form.get('domain', '').strip() or None

        if not command:
            return "Process command is required", 400

        # Validate domain if provided
        if domain:
            from utils import validate_domain_format, check_domain_uniqueness
            validation = validate_domain_format(domain)
            if not validation.get("valid"):
                print("invalid domain")
                flash(f"Invalid domain: {validation.get('error')}", "danger")
                domain = None  # Don't save invalid domain
            else:
                # Check uniqueness
                uniqueness = check_domain_uniqueness(domain, current_process_name=name)
                if not uniqueness.get("unique"):
                    flash(f"Domain already in use by: {', '.join(uniqueness.get('conflicts', []))}", "warning")
                    # Still save it but show warning

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
        process.domain = domain

        try:
            db.session.add(process)
            db.session.commit()
            if domain:
                flash(f"Settings saved successfully. Domain '{domain}' configured.", "success")
            else:
                flash("Settings saved successfully.", "success")
        except Exception as e:
            db.session.rollback()
            return f"Database commit failed: {str(e)}", 500

        return redirect(url_for('process.console', name=new_name))

    # Cloudflare context
    current_user_id = session.get("user_id")
    user_settings = UserSettings.get_or_create(current_user_id) if current_user_id else None
    cloudflare_configured = bool(user_settings and user_settings.cloudflare_api_token)
    server_ip = get_server_ip()

    return render_template(
        'process/settings.html',
        page_title="Settings",
        process=process,
        types=types,
        cloudflare_configured=cloudflare_configured,
        server_ip=server_ip
    )


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


@process_routes.route('/cloudflare/<string:name>/create', methods=['POST'])
@owner_or_subuser_required()
def cloudflare_create(name):
    process = find_process_by_name(name)
    if not process:
        return jsonify({"success": False, "error": "Process not found"}), 404

    data = request.get_json() or {}
    record_type = (data.get('type') or 'A').upper()
    record_name = (data.get('name') or process.domain or '').strip().lstrip('*.')
    value = (data.get('value') or '').strip()
    proxied = bool(data.get('proxied', False))

    if not record_name:
        return jsonify({"success": False, "error": "Set a domain on the process first."}), 400

    # Fallback to server IP for A records when value omitted
    if record_type == 'A' and not value:
        value = get_server_ip() or ''

    if not value:
        return jsonify({"success": False, "error": "Record value is required."}), 400

    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"success": False, "error": "Not authenticated"}), 401

    user_settings = UserSettings.get_or_create(int(user_id))
    token = user_settings.cloudflare_api_token if user_settings else None
    if not token:
        return jsonify({"success": False, "error": "Cloudflare API token is not configured in Settings."}), 400

    zone_name = extract_zone_name(process.domain or record_name)
    zone_id = get_zone_id(token, zone_name)
    if not zone_id:
        return jsonify({"success": False, "error": f"Cloudflare zone not found for {zone_name}."}), 404

    result = create_dns_record(token, zone_id, record_type, record_name, value, proxied=proxied)
    if not result.get('success'):
        return jsonify({"success": False, "error": result.get('errors') or result.get('messages') or "Failed to create DNS record"}), 400

    return jsonify({"success": True, "message": "DNS record created", "data": result.get('result')})


@process_routes.route('/cloudflare/<string:name>/delete', methods=['POST'])
@owner_or_subuser_required()
def cloudflare_delete(name):
    process = find_process_by_name(name)
    if not process:
        return jsonify({"success": False, "error": "Process not found"}), 404

    data = request.get_json() or {}
    record_type = (data.get('type') or 'A').upper()
    record_name = (data.get('name') or process.domain or '').strip().lstrip('*.')

    if not record_name:
        return jsonify({"success": False, "error": "Record name is required."}), 400

    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"success": False, "error": "Not authenticated"}), 401

    user_settings = UserSettings.get_or_create(int(user_id))
    token = user_settings.cloudflare_api_token if user_settings else None
    if not token:
        return jsonify({"success": False, "error": "Cloudflare API token is not configured in Settings."}), 400

    zone_name = extract_zone_name(process.domain or record_name)
    zone_id = get_zone_id(token, zone_name)
    if not zone_id:
        return jsonify({"success": False, "error": f"Cloudflare zone not found for {zone_name}."}), 404

    record_id = find_dns_record(token, zone_id, record_name, record_type)
    if not record_id:
        return jsonify({"success": False, "error": "DNS record not found in Cloudflare."}), 404

    result = delete_dns_record(token, zone_id, record_id)
    if not result.get('success'):
        return jsonify({"success": False, "error": result.get('errors') or result.get('messages') or "Failed to delete DNS record"}), 400

    return jsonify({"success": True, "message": "DNS record deleted"})


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

    # Log activity
    try:
        ActivityLog.log_activity(
            user_id=session.get('user_id'),
            username=session.get('username'),
            action='rebuilt_process',
            target=name,
            details="Process rebuild initiated",
            request_obj=request
        )
    except Exception as log_error:
        print(f"Failed to log activity: {log_error}")

    return redirect(url_for('process.console', name=process.name))


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

        # Log activity
        try:
            ActivityLog.log_activity(
                user_id=session.get('user_id'),
                username=session.get('username'),
                action='added_subuser',
                target=name,
                details=f"Added subuser: {email}",
                request_obj=request
            )
        except Exception as log_error:
            print(f"Failed to log activity: {log_error}")

        flash('Invitation has been sent!', 'success')
        return redirect(url_for('process.subusers', name=name))

    return redirect(url_for('process.subusers', name=name))


@process_routes.route('/subusers/<string:name>/delete/<int:user_id>', methods=['POST'])
@owner_or_subuser_required()
def delete_subuser(name, user_id):
    sub_user = SubUser.query.filter_by(id=user_id).first()
    if sub_user:
        subuser_email = sub_user.email  # Store email before deletion
        db.session.delete(sub_user)
        db.session.commit()
        
        # Log activity
        try:
            ActivityLog.log_activity(
                user_id=session.get('user_id'),
                username=session.get('username'),
                action='deleted_subuser',
                target=name,
                details=f"Removed subuser: {subuser_email}",
                request_obj=request
            )
        except Exception as log_error:
            print(f"Failed to log activity: {log_error}")
        
        flash(f"Sub-user with email {subuser_email} has been removed.", "success")
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

        process = find_process_by_name(name)
        if not process:
            return jsonify({"error": "Process not found"}), 404

        command = process.command
        if action == "stop":
            container_id = get_container_id(name)
            if not container_id:
                return jsonify({"error": "Cannot determine container"}), 400

            command_pattern = f"[{command[0]}]{command[1:]}" if command else ""
            cron_line = (
                f"{schedule} root docker exec {container_id} "
                f"sh -c \"pkill -9 -P \\$(pgrep -f '{command_pattern}'); kill -9 \\$(pgrep -f '{command_pattern}')\""
            )
        elif action == "start":

            container_id = get_container_id(name)
            if not container_id:
                return jsonify({"error": "Cannot determine container"}), 400
            cron_line = f"{schedule} root docker exec {container_id} {command}"
        else:
            return jsonify({"error": "Invalid action"}), 400

        cron_file = f"/etc/cron.d/{name.replace('.', '_')}_power_event"
        cron_command = f"echo {shlex.quote(cron_line)} | sudo tee -a {cron_file} > /dev/null"

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


@process_routes.route('/metrics/<string:name>', methods=['GET'])
@owner_or_subuser_required()
def get_process_metrics(name):
    """
    Get real-time CPU and memory metrics for a process.
    Returns JSON with cpu_percent, memory_percent, memory_mb.
    """
    process = find_process_by_name(name)
    if not process:
        return jsonify({"error": "Process not found"}), 404

    try:
        container_id = get_container_id(name)
        if not container_id:
            return jsonify({
                "cpu_percent": 0,
                "memory_percent": 0,
                "memory_mb": 0,
                "status": "stopped"
            })

        # Get container stats using docker stats
        result = subprocess.run(
            ['docker', 'stats', '--no-stream', '--format', 
             '{{.CPUPerc}}|{{.MemPerc}}|{{.MemUsage}}', container_id],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0 and result.stdout.strip():
            try:
                stats = result.stdout.strip().split('|')
                
                # Clean and parse CPU percent
                cpu_str = stats[0].replace('%', '').strip()
                cpu_percent = float(cpu_str) if cpu_str else 0.0
                
                # Clean and parse memory percent
                mem_str = stats[1].replace('%', '').strip()
                memory_percent = float(mem_str) if mem_str else 0.0
                
                # Parse memory usage (e.g., "123.4MiB / 1.5GiB")
                mem_usage = stats[2].split('/')[0].strip()
                memory_mb = 0.0
                
                if 'GiB' in mem_usage:
                    memory_mb = float(mem_usage.replace('GiB', '').strip()) * 1024
                elif 'MiB' in mem_usage:
                    memory_mb = float(mem_usage.replace('MiB', '').strip())
                elif 'KiB' in mem_usage:
                    memory_mb = float(mem_usage.replace('KiB', '').strip()) / 1024
                elif 'B' in mem_usage and 'iB' not in mem_usage:
                    memory_mb = float(mem_usage.replace('B', '').strip()) / (1024 * 1024)

                return jsonify({
                    "cpu_percent": round(cpu_percent, 2),
                    "memory_percent": round(memory_percent, 2),
                    "memory_mb": round(memory_mb, 2),
                    "status": "running"
                })
            except (ValueError, IndexError) as parse_error:
                print(f"[metrics] Failed to parse stats for {name}: {result.stdout} - Error: {parse_error}")
                return jsonify({
                    "cpu_percent": 0,
                    "memory_percent": 0,
                    "memory_mb": 0,
                    "status": "error",
                    "error": f"Failed to parse stats: {str(parse_error)}"
                }), 500
        else:
            print(f"[metrics] Docker stats failed for {name}: returncode={result.returncode}, stderr={result.stderr}")
            return jsonify({
                "cpu_percent": 0,
                "memory_percent": 0,
                "memory_mb": 0,
                "status": "error",
                "error": f"Docker stats command failed: {result.stderr}"
            }), 500

    except subprocess.TimeoutExpired:
        return jsonify({
            "error": "Timeout getting container metrics"
        }), 504
    except Exception as e:
        return jsonify({
            "error": f"Failed to get metrics: {str(e)}"
        }), 500


@process_routes.route('/env-vars/<string:name>', methods=['POST'])
@owner_or_subuser_required()
def save_env_vars(name):
    """
    Save environment variables for a process.
    Expects JSON: {"env_vars": [{"key": "VAR_NAME", "value": "var_value"}, ...]}
    """
    process = find_process_by_name(name)
    if not process:
        return jsonify({"success": False, "error": "Process not found"}), 404

    try:
        data = request.get_json()
        if not data or 'env_vars' not in data:
            return jsonify({"success": False, "error": "Missing env_vars in request"}), 400

        env_vars = data['env_vars']
        
        # Get the docker-compose.yml path
        process_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
        compose_file = os.path.join(process_dir, 'docker-compose.yml')
        
        if not os.path.exists(compose_file):
            return jsonify({"success": False, "error": "docker-compose.yml not found"}), 404

        # Read current docker-compose.yml
        with open(compose_file, 'r') as f:
            compose_data = yaml.safe_load(f)

        # Update environment variables for the service
        if 'services' not in compose_data:
            return jsonify({"success": False, "error": "Invalid docker-compose.yml format"}), 400

        # Assume the service name matches the process name
        service_name = name
        if service_name not in compose_data['services']:
            # Try to get the first service
            service_name = list(compose_data['services'].keys())[0]

        if 'environment' not in compose_data['services'][service_name]:
            compose_data['services'][service_name]['environment'] = {}

        # Update environment variables
        env_dict = {var['key']: var['value'] for var in env_vars if var['key']}
        compose_data['services'][service_name]['environment'].update(env_dict)

        # Write back to docker-compose.yml
        with open(compose_file, 'w') as f:
            yaml.dump(compose_data, f, default_flow_style=False)

        return jsonify({
            "success": True, 
            "message": "Environment variables saved. Restart the process for changes to take effect.",
            "vars_saved": len(env_dict)
        })

    except yaml.YAMLError as e:
        return jsonify({"success": False, "error": f"YAML parsing error: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to save environment variables: {str(e)}"}), 500


@process_routes.route('/validate-domain/<string:name>', methods=['POST'])
@owner_or_subuser_required()
def validate_domain(name):
    """
    Validate domain and get comprehensive status including DNS, SSL, and uniqueness checks.
    Expects JSON: {"domain": "example.com"}
    """
    from utils import get_domain_status  # type: ignore
    
    process = find_process_by_name(name)
    if not process:
        return jsonify({"error": "Process not found"}), 404

    try:
        data = request.get_json()
        if not data or 'domain' not in data:
            return jsonify({"error": "Missing domain in request"}), 400

        domain = data['domain'].strip()
        
        # Get comprehensive domain status
        status = get_domain_status(domain, process_name=name)
        
        return jsonify(status)

    except Exception as e:
        return jsonify({"error": f"Failed to validate domain: {str(e)}"}), 500
