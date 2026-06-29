from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import time

import yaml
from datetime import datetime, UTC, timedelta
from flask import (
    Blueprint,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    stream_with_context,
    url_for,
)
from db import db
from models.process import Process
from models.git import GitIntegration
from models.subuser import SubUser
from models.activity_log import ActivityLog
from decorators import owner_or_subuser_required, owner_required
from models.user import User
from utils import find_process_by_name, find_types, get_process_status, generate_random_string, send_email, execute_handler, get_server_ip
from utils.cloudflare import (
    extract_zone_name,
    get_zone_id,
    create_dns_record,
    update_dns_record,
    find_dns_record,
    delete_dns_record,
    list_dns_records,
)
from models.user_settings import UserSettings
from utils.discord import DiscordNotifier, get_user_discord_settings
from runtime import get_runtime

process_routes = Blueprint('process', __name__)

PROCESS_DIRECTORY = 'active-servers'
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, 'active-servers')

# Lightweight Redis-backed cache to avoid repeated docker status calls during rapid page loads
# Uses Flask-Caching Redis backend (configured in app.py) for cross-worker consistency
import json as _json
import redis as _redis

_PROCESS_CACHE_TTL = 5  # seconds
_redis_client = None


def _get_redis():
    """Lazy-init a Redis client for the process status cache."""
    global _redis_client
    if _redis_client is None:
        _redis_client = _redis.StrictRedis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            decode_responses=True
        )
    return _redis_client

# Global cache for batch docker status lookups (delegated to runtime layer)
_DOCKER_PS_CACHE = {}
_DOCKER_PS_CACHE_TIMESTAMP = 0
_DOCKER_PS_CACHE_TTL = 3  # seconds


def _get_all_container_statuses():
    """Fetch container statuses via centralized DockerRuntime."""
    return get_runtime().get_all_container_statuses()


def get_all_container_stats():
    """Fetch all container stats via runtime supervisors / DockerRuntime."""
    return get_runtime().get_all_metrics()


def _make_process_cache_key(user_id, role):
    return f"{role or 'user'}:{user_id or 'anon'}"


def send_discord_power_notification(process, action, success=True, details=None):
    """Send a Discord power-action notification for a process if enabled."""
    try:
        discord_settings = get_user_discord_settings(process.owner_id)
        if not discord_settings or not discord_settings.get('notify_power_actions'):
            return

        actor_username = session.get('username')
        if not actor_username:
            actor_id = session.get('user_id')
            if actor_id:
                actor = User.query.get(actor_id)
                actor_username = actor.username if actor else None
        if not actor_username:
            owner = User.query.get(process.owner_id)
            actor_username = owner.username if owner else 'Unknown'

        DiscordNotifier.notify_power_action(
            webhook_url=discord_settings['webhook_url'],
            action=action,
            process_name=process.name,
            process_type=process.type,
            user=actor_username,
            success=success,
            details=details
        )
    except Exception as discord_error:
        print(f"Failed to send Discord notification: {discord_error}")


def invalidate_process_cache(cache_key=None):
    """Invalidate cached process status results (stored in Redis)."""
    try:
        r = _get_redis()
        if cache_key:
            r.delete(f"process_cache:{cache_key}")
        else:
            for key in r.scan_iter("process_cache:*"):
                r.delete(key)
    except Exception:
        pass
    get_runtime().invalidate_docker_cache()


def get_container_id(process_name):
    """Get container ID via runtime layer."""
    return get_runtime().get_container_id(process_name)


def get_main_command_for_container(container_id, fallback_command=""):
    from runtime import run_sync

    main_cmd = run_sync(get_runtime().docker.inspect_main_command(container_id))
    return main_cmd if main_cmd else fallback_command


def get_process_pid_in_container(container_id, command):
    if not container_id or not command:
        return None

    from runtime import run_sync

    pid = run_sync(get_runtime().docker.get_process_pid(container_id, command))
    return pid


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


def calculate_uptime(startup_date):
    """Calculate uptime from a Docker container's StartedAt timestamp (UTC ISO 8601)."""
    from datetime import timezone

    # Docker returns StartedAt in UTC (with trailing Z or +00:00)
    startup_str = startup_date.rstrip('Z')
    startup_datetime = datetime.fromisoformat(startup_str).replace(tzinfo=timezone.utc)

    current_time = datetime.now(timezone.utc)

    uptime = current_time - startup_datetime

    seconds = int(uptime.total_seconds())
    if seconds < 0:
        seconds = 0

    weeks = seconds // (7 * 24 * 3600)
    days = (seconds % (7 * 24 * 3600)) // 86400
    hours = (seconds % 86400) // 3600
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

    # Check Redis cache
    try:
        r = _get_redis()
        cached_json = r.get(f"process_cache:{cache_key}")
        if cached_json:
            return _json.loads(cached_json)
    except Exception:
        pass  # Redis unavailable, proceed without cache
    
    user = User.query.filter_by(id=user_id).first()

    owned_processes = Process.query.filter_by(owner_id=user_id).all()
    sub_user_processes = Process.query.join(SubUser, Process.name == SubUser.process).filter(SubUser.email == user.email).all()

    processes = owned_processes + sub_user_processes

    if session.get("role") == "admin":
        processes = Process.query.all()

    # PERFORMANCE: Fetch ALL container statuses in a single docker call
    # instead of running 'docker-compose ps' per container (saves ~1-3s per container)
    container_statuses = _get_all_container_statuses()

    def _fetch_status_fast(process):
        """Fast status lookup using pre-fetched batch data."""
        container_info = container_statuses.get(process.name)
        if container_info:
            state = container_info['state']
            if state == 'running':
                status = 'Running'
            elif state in ('exited', 'dead', 'created'):
                status = 'Exited'
            elif state == 'restarting':
                status = 'Restarting'
            elif state == 'paused':
                status = 'Paused'
            else:
                status = 'Unknown'
        else:
            status = 'Exited'

        return process.name, {
            "id": process.id,
            "type": process.type,
            "command": process.command,
            "file_location": process.file_location,
            "name": process.name,
            "status": status,
            "created_at": process.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }

    # No threading needed - batch data is already fetched
    for p in processes:
        name, entry = _fetch_status_fast(p)
        if entry is not None:
            process_dict[name] = entry

    # Store in Redis cache with TTL
    try:
        r = _get_redis()
        r.setex(f"process_cache:{cache_key}", _PROCESS_CACHE_TTL, _json.dumps(process_dict))
    except Exception:
        pass  # Redis unavailable — will just skip caching
    return process_dict


@process_routes.route('/', methods=['GET'])
def get_process():
    processes = load_process()
    return jsonify(processes)


@process_routes.route('/all-metrics', methods=['GET'])
def get_all_process_metrics():
    """
    Fetch CPU/memory metrics for ALL containers in a single docker stats call.
    Returns JSON mapping process name -> {cpu_percent, memory_percent, memory_mb}.
    Replaces N individual /metrics/<name> calls from the dashboard.
    """
    stats = get_all_container_stats()
    return jsonify(stats)


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
            # Cleanup: remove DB entry and process directory
            try:
                db.session.delete(new_process)
                db.session.commit()
            except Exception:
                db.session.rollback()
            try:
                if os.path.exists(process_dir):
                    import shutil
                    shutil.rmtree(process_dir)
            except Exception:
                pass
            return jsonify({"error": compose_result.message if not compose_result.success else docker_result.message}), 400

        up_result = get_runtime().compose_up(process_name)
        if not up_result.get("success"):
            raise subprocess.CalledProcessError(1, "docker compose up", up_result.get("stderr", ""))

        get_runtime().get_supervisor(process_name, process_type)
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
        # Cleanup: remove DB entry and process directory if created
        try:
            process = Process.query.filter_by(name=process_name).first()
            if process:
                db.session.delete(process)
                db.session.commit()
        except Exception:
            db.session.rollback()
        try:
            if os.path.exists(process_dir):
                import shutil
                shutil.rmtree(process_dir)
        except Exception:
            pass
        return jsonify({"error": f"Failed to create process directory: {e}"}), 500
    except subprocess.CalledProcessError as e:
        # Cleanup: remove DB entry and process directory if created
        try:
            process = Process.query.filter_by(name=process_name).first()
            if process:
                db.session.delete(process)
                db.session.commit()
        except Exception:
            db.session.rollback()
        try:
            if os.path.exists(process_dir):
                import shutil
                shutil.rmtree(process_dir)
        except Exception:
            pass
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
                get_runtime().compose_down(name)
                get_runtime().unregister_process(name)
            except Exception as e:
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
        result = get_runtime().start(name, process.type)
        if result.get("success"):
            update_process_runtime_metadata(process)
            invalidate_process_cache()
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
            send_discord_power_notification(process, action='started', success=True)
            return jsonify({
                "message": result.get("message", f"Process '{name}' started successfully."),
                "status": get_process_status(process.name),
                "ok": True
            })
        return jsonify({
            "error": result.get("error", "Failed to start process"),
            "ok": False
        }), 500
    except Exception as e:
        return jsonify({
            "error": f"Unexpected error starting '{name}': {str(e)}",
            "ok": False
        }), 500


@process_routes.route('/stop/<string:name>', methods=['POST'])
@owner_or_subuser_required()
def stop_process_console(name):
    process = find_process_by_name(name)
    if not process:
        return jsonify({"error": "Process not found"}), 404

    try:
        result = get_runtime().stop(name, process.type)
        if result.get("success"):
            process.process_pid = None
            try:
                db.session.add(process)
                db.session.commit()
            except Exception as db_err:
                db.session.rollback()
                print(f"[process_metadata] Failed to clear PID for {name}: {db_err}")

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
            send_discord_power_notification(process, action='stopped', success=True)
            return jsonify({"message": result.get("message", f"Process {name} stopped successfully.")})
        return jsonify({"error": result.get("error", "Failed to stop process")}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@process_routes.route('/restart/<string:name>', methods=['POST'])
@owner_or_subuser_required()
def restart_process_console(name):
    process = find_process_by_name(name)
    if not process:
        return jsonify({"error": "Process not found", "ok": False}), 404

    try:
        result = get_runtime().restart(name, process.type)
        if not result.get("success"):
            return jsonify({
                "error": result.get("error", "Failed to restart process"),
                "ok": False
            }), 500

        update_process_runtime_metadata(process)
        invalidate_process_cache()

        try:
            ActivityLog.log_activity(
                user_id=session.get('user_id'),
                username=session.get('username'),
                action='restarted_process',
                target=name,
                details="Process restarted successfully",
                request_obj=request
            )
        except Exception as log_error:
            print(f"Failed to log activity: {log_error}")

        send_discord_power_notification(process, action='restarted', success=True)

        return jsonify({
            "message": f"Process '{name}' restarted successfully.",
            "status": get_process_status(process.name),
            "ok": True
        })
    except Exception as e:
        return jsonify({
            "error": f"Unexpected error restarting '{name}': {str(e)}",
            "ok": False
        }), 500


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
        startup_date = get_runtime().get_uptime_started_at(name)
        if not startup_date:
            return jsonify({'uptime': '0w 0d 0h 0m 0s', 'error': 'Process is not running.'})

        uptime = calculate_uptime(startup_date)
        return jsonify({'uptime': uptime})
    except Exception as e:
        return jsonify({'uptime': '0w 0d 0h 0m 0s', 'error': str(e)})


@process_routes.route('/console/<string:name>/logs', methods=['GET'])
@owner_or_subuser_required()
def console_stream_logs(name):
    process = find_process_by_name(name)
    if not process:
        return jsonify({"error": "Process not found"}), 404

    return Response(
        stream_with_context(get_runtime().subscribe_console(name, process.type)),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
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

        # Execute the command via runtime (output is published to the event bus)
        result = get_runtime().execute(
            name, command, working_dir, timeout, process.type
        )

        if not result['success']:
            error_msg = result.get("error", "Command failed")
            if "container not running" in error_msg.lower():
                result["error"] = "Cannot execute command: Container is not running. Start the process first."
            elif "timeout" in error_msg.lower():
                result["error"] = (
                    f"Command timed out after {timeout}s. "
                    "Try increasing the timeout or check if the command is stuck."
                )
            elif "permission denied" in error_msg.lower():
                result["error"] = (
                    f"Permission denied: {error_msg}. "
                    "The container user may lack necessary permissions."
                )

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

        result = get_runtime().execute_interactive(name, command, working_dir, process.type)

        if result['success']:
            return jsonify({
                "success": True,
                "message": result["message"],
                "process_pid": result["process"].pid
            })
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
        result = get_runtime().execute_interactive(name, shell_command, working_dir, process.type)

        if result['success']:
            return jsonify({
                "success": True,
                "message": "Shell session started",
                "process_pid": result["process"].pid,
                "working_dir": working_dir,
                "shell": shell
            })
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
        result = get_runtime().clear_logs(name)
        if result.get("success"):
            return jsonify({"success": True, "message": result.get("message", "Logs cleared successfully")})
        return jsonify({"success": False, "error": result.get("error", "Failed to clear logs")}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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


@process_routes.route('/cloudflare/<string:name>', methods=['GET'])
@owner_or_subuser_required()
def cloudflare(name):
    process = find_process_by_name(name)
    if not process:
        return redirect(url_for('dashboard'))

    user_id = session.get("user_id")
    user_settings = UserSettings.get_or_create(user_id) if user_id else None
    cloudflare_configured = bool(user_settings and user_settings.cloudflare_api_token)
    server_ip = get_server_ip()

    return render_template(
        'process/cloudflare.html',
        page_title="Cloudflare",
        process=process,
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
    record_id = data.get('record_id')

    if not record_name and not record_id:
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

    if not record_id:
        record_id = find_dns_record(token, zone_id, record_name, record_type)
        if not record_id:
            return jsonify({"success": False, "error": "DNS record not found in Cloudflare."}), 404

    result = delete_dns_record(token, zone_id, record_id)
    if not result.get('success'):
        return jsonify({"success": False, "error": result.get('errors') or result.get('messages') or "Failed to delete DNS record"}), 400

    return jsonify({"success": True, "message": "DNS record deleted"})


@process_routes.route('/cloudflare/<string:name>/update', methods=['POST'])
@owner_or_subuser_required()
def cloudflare_update(name):
    process = find_process_by_name(name)
    if not process:
        return jsonify({"success": False, "error": "Process not found"}), 404

    data = request.get_json() or {}
    record_id = data.get('record_id')
    record_type = (data.get('type') or 'A').upper()
    record_name = (data.get('name') or process.domain or '').strip().lstrip('*.')
    value = (data.get('value') or '').strip()
    proxied = bool(data.get('proxied', False))

    if not record_id:
        return jsonify({"success": False, "error": "record_id is required for update."}), 400
    if not record_name:
        return jsonify({"success": False, "error": "Record name is required."}), 400
    if not value:
        return jsonify({"success": False, "error": "Record value is required."}), 400

    uid = session.get('user_id')
    if not uid:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    user_settings = UserSettings.get_or_create(int(uid))
    token = user_settings.cloudflare_api_token if user_settings else None
    if not token:
        return jsonify({"success": False, "error": "Cloudflare API token is not configured in Settings."}), 400

    zone_name = extract_zone_name(process.domain or record_name)
    zone_id = get_zone_id(token, zone_name)
    if not zone_id:
        return jsonify({"success": False, "error": f"Cloudflare zone not found for {zone_name}."}), 404

    result = update_dns_record(token, zone_id, record_id, record_type, record_name, value, proxied=proxied)
    if not result.get('success'):
        return jsonify({"success": False, "error": result.get('errors') or result.get('messages') or "Failed to update DNS record"}), 400

    return jsonify({"success": True, "message": "DNS record updated", "data": result.get('result')})


@process_routes.route('/cloudflare/<string:name>/records', methods=['GET'])
@owner_or_subuser_required()
def cloudflare_records(name):
    process = find_process_by_name(name)
    if not process:
        return jsonify({"success": False, "error": "Process not found"}), 404

    uid = session.get('user_id')
    if not uid:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    user_settings = UserSettings.get_or_create(int(uid))
    token = user_settings.cloudflare_api_token if user_settings else None
    if not token:
        return jsonify({"success": False, "error": "Cloudflare API token is not configured in Settings."}), 400

    domain = process.domain or ''
    zone_name = extract_zone_name(domain)
    zone_id = get_zone_id(token, zone_name)
    if not zone_id:
        return jsonify({"success": False, "error": f"Cloudflare zone not found for {zone_name}."}), 404

    result = list_dns_records(token, zone_id, domain or None)
    if not result.get('success'):
        return jsonify({"success": False, "error": result.get('errors') or result.get('messages') or "Failed to list DNS records"}), 400

    records = result.get('result') or []
    return jsonify({"success": True, "records": records})


@process_routes.route('/rebuild/<name>', methods=['POST'])
@owner_required()
def settings_rebuild(name):
    process = find_process_by_name(name)
    if not process:
        return redirect(url_for('process.index'))

    project_dir = os.path.join(ACTIVE_SERVERS_DIR, name)

    if not os.path.isdir(project_dir):
        return jsonify({"error": "Project directory not found"}), 404

    get_runtime().rebuild_async(name, process.type)

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

    send_discord_power_notification(
        process,
        action='rebuilt',
        success=True,
        details='Rebuild initiated'
    )

    return redirect(url_for('process.console', name=process.name))


@process_routes.route('/subusers/<string:name>', methods=['GET'])
@owner_or_subuser_required()
def subusers(name):
    process = find_process_by_name(name)
    return render_template('process/subusers.html', page_title="Sub Users", process=process)


@process_routes.route('/subusers/<string:name>/api/list', methods=['GET'])
@owner_or_subuser_required()
def subusers_list(name):
    process = find_process_by_name(name)
    if not process:
        return jsonify({"success": False, "error": "Process not found"}), 404

    users = SubUser.query.filter_by(process=name).order_by(SubUser.created_at.desc()).all()
    return jsonify({
        "success": True,
        "users": [user.as_dict() for user in users]
    })


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

        return redirect(url_for('process.schedule', name=name))

    return render_template('process/schedule.html', page_title="Schedule", process=process)


@process_routes.route('/schedule/<string:name>/api/jobs', methods=['GET'])
@owner_or_subuser_required()
def schedule_jobs(name):
    process = find_process_by_name(name)
    if not process:
        return jsonify({"success": False, "error": "Process not found"}), 404

    cron_jobs = get_current_cron_jobs(name)
    if isinstance(cron_jobs, dict):
        return jsonify({"success": False, "error": cron_jobs.get('error', 'Failed to load cron jobs')}), 500

    return jsonify({"success": True, "jobs": cron_jobs})


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
        metrics = get_runtime().get_metrics(name)
        return jsonify(metrics)
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
