from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import base64
import psutil
import smtplib
from flask import current_app
import os
import subprocess
import random
import string
import importlib
import textwrap
import re
import socket
import dns.resolver
from datetime import datetime
from collections import defaultdict
from queue import Queue
from models.process import Process

# Import the live_log_streams from routes/process.py
live_log_streams = defaultdict(Queue)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))
ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, 'active-servers')


def get_process_status(name):
    process = find_process_by_name(name)
    if not process:
        return {"error": "Process not found"}

    # Check if this is an always-running container
    if is_always_running_container(name):
        # Use the new process-aware status checking
        return check_process_running_in_container(name)
    else:
        # Use traditional container status checking for legacy containers
        try:
            process_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
            os.chdir(process_dir)

            result = subprocess.run(['docker-compose', 'ps', '-q', name], capture_output=True, text=True, check=True)
            container_id = result.stdout.strip()

            if not container_id:
                return {"process": name, "status": "Exited"}

            result = subprocess.run(['docker', 'inspect', '--format', '{{.State.Status}}', container_id], capture_output=True, text=True)

            if result.returncode != 0:
                return {"error": "Failed to get process status from docker inspect."}

            container_status = result.stdout.strip()

            if container_status == 'running':
                return {"process": name, "status": "Running"}
            
            return {"process": name, "status": "Exited"}

        except subprocess.CalledProcessError as e:
            return {"error": f"Failed to get process status: {e.stderr}"}
        except Exception as e:
            return {"error": str(e)}

    
def find_process_by_name(name):
    with current_app.app_context():
        return Process.query.filter_by(name=name).first()


def find_process_by_id(process_id):
    with current_app.app_context():
        return Process.query.get(process_id)


SMTP_SERVER = os.getenv("MAIL_SERVER", "")
SMTP_PORT = int(os.getenv("MAIL_PORT", "0"))
EMAIL_ADDRESS = os.getenv("MAIL_USERNAME", "")
EMAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")


def send_email(to: str, subject: str, body: str, type: str = 'auth', attachment: str = ""):
    message = MIMEMultipart()
    message["From"] = f"Server Manager <{type}@tijnn.dev>"
    message["To"] = to
    message["Subject"] = subject
    message.attach(MIMEText(body, "html"))

    if attachment:
        part = MIMEBase('application', 'octet-stream')
        with open(attachment, 'rb') as file:
            part.set_payload(file.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename={attachment}')
        message.attach(part)

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, to, message.as_string())
            return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False
    

def generate_random_string(length: int) -> str:
    """Generates a random string of a specified length."""
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))


def check_process_running_in_container(name):
    """Check if the main process is running inside the container"""
    try:
        process_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
        os.chdir(process_dir)

        # Get container ID
        result = subprocess.run(['docker-compose', 'ps', '-q', name], capture_output=True, text=True, check=True)
        container_id = result.stdout.strip()

        if not container_id:
            return {"status": "Container Not Running", "container_running": False}

        # Check if container is running
        result = subprocess.run(['docker', 'inspect', '--format', '{{.State.Status}}', container_id], 
                              capture_output=True, text=True)
        
        container_status = result.stdout.strip()
        
        if result.returncode != 0 or container_status != 'running':
            return {"status": "Container Not Running", "container_running": False}

        # Get the main command from environment variable
        result = subprocess.run(['docker', 'inspect', '--format', '{{range .Config.Env}}{{println .}}{{end}}', container_id],
                              capture_output=True, text=True)
        
        
        main_command = None
        for line in result.stdout.split('\n'):
            if line.startswith('MAIN_COMMAND='):
                main_command = line.split('=', 1)[1].strip('"')
                break

        if not main_command:
            return {"status": "Running", "container_running": True, "process_running": True}

        # Check if the main process is running inside the container
        result = subprocess.run(['docker', 'exec', container_id, 'ps', 'aux'], 
                              capture_output=True, text=True)
        
        if result.returncode != 0:
            return {"status": "Process Stopped", "container_running": True, "process_running": False}

        # Parse process list to find our main command
        processes = result.stdout
        command_parts = main_command.split()
        
        # Define process name mappings for common web servers
        # These map the MAIN_COMMAND to the actual process names that run
        process_name_mappings = {
            'apache2-foreground': ['apache2', 'httpd'],
            'php-fpm': ['php-fpm'],
            'nginx': ['nginx'],
            'vite': ['node', 'vite'],
            'npm': ['node', 'npm'],
            'node': ['node'],
            'minecraft': ['java'],
            'java': ['java'],
            'python': ['python'],
            'python3': ['python3'],
        }
        
        # Determine what processes to look for
        search_terms = []
        for cmd_part in command_parts:
            if cmd_part in process_name_mappings:
                search_terms.extend(process_name_mappings[cmd_part])
            elif len(cmd_part) > 2:  # Only use meaningful parts
                search_terms.append(cmd_part)
        
        # If no specific search terms, use original command parts
        if not search_terms:
            search_terms = [part for part in command_parts if len(part) > 2]
        
        # Look for the main command in the process list (exclude zombie processes and ps/grep itself)
        process_running = False
        matching_processes = []
        for line in processes.split('\n')[1:]:  # Skip header
            if line.strip():
                # Skip ps aux and grep commands themselves
                if 'ps aux' in line or 'grep' in line:
                    continue
                    
                # Check if this is a zombie process (contains <defunct> or Z state)
                if '<defunct>' in line or ' Z ' in line:
                    continue
                    
                # Check if any search term appears in the process line
                for term in search_terms:
                    if term in line:
                        process_running = True
                        matching_processes.append(line.strip())
                        break
        
        if process_running:
            return {"status": "Running", "container_running": True, "process_running": True}
        else:
            return {"status": "Process Stopped", "container_running": True, "process_running": False}

    except subprocess.CalledProcessError as e:
        return {"status": "Error", "error": f"Failed to check process status: {e.stderr}"}
    except Exception as e:
        return {"status": "Error", "error": str(e)}


def start_process_in_container(name):
    """Start the main process inside an already running container with proper log streaming"""
    try:
        process_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
        os.chdir(process_dir)

        # Get container ID
        result = subprocess.run(['docker-compose', 'ps', '-q', name], capture_output=True, text=True, check=True)
        container_id = result.stdout.strip()

        if not container_id:
            # Container not running, start it first
            subprocess.run(['docker-compose', 'up', '-d'], check=True)
            # Wait for container to be ready
            import time
            time.sleep(2)
            
            # Get new container ID
            result = subprocess.run(['docker-compose', 'ps', '-q', name], capture_output=True, text=True, check=True)
            container_id = result.stdout.strip()

        # Get the main command from environment
        result = subprocess.run(['docker', 'inspect', '--format', '{{range .Config.Env}}{{println .}}{{end}}', container_id],
                              capture_output=True, text=True)
        
        main_command = None
        for line in result.stdout.split('\n'):
            if line.startswith('MAIN_COMMAND='):
                main_command = line.split('=', 1)[1].strip('"')
                break

        if not main_command:
            return {"success": False, "error": "No MAIN_COMMAND found in container environment"}

        # First, let's stop any existing processes to clean up zombies
        stop_process_in_container(name)

        # Clear the old log file and create a fresh one
        log_file = f"/tmp/{name}_process.log"
        subprocess.run(['docker', 'exec', container_id, 'sh', '-c', f'> {log_file}'], 
                      capture_output=True, text=True)
        
        # Create a wrapper script that logs both stdout and stderr
        wrapper_script = '''#!/bin/bash
cd /app
which npm | tee -a {log_file} 2>&1 || echo "npm not found" | tee -a {log_file}
which node | tee -a {log_file} 2>&1 || echo "node not found" | tee -a {log_file}
exec {main_command} 2>&1 | tee -a {log_file}
'''.format(log_file=log_file, main_command=main_command)
        
        # First, create the script content in a temporary file and copy it to container
        wrapper_script.encode('utf-8')
        
        # Write script using docker exec with proper escaping
        script_creation_command = f'''cat > /tmp/start_process.sh << 'EOF'
{wrapper_script}
EOF
chmod +x /tmp/start_process.sh'''
        
        script_result = subprocess.run(['docker', 'exec', container_id, 'sh', '-c', script_creation_command], 
                                     capture_output=True, text=True)
        
        if script_result.returncode != 0:
            return {"success": False, "error": f"Failed to create wrapper script: {script_result.stderr}"}
        
        # Verify the script was created successfully
        verify_result = subprocess.run(['docker', 'exec', container_id, 'test', '-f', '/tmp/start_process.sh'], 
                                     capture_output=True, text=True)
        if verify_result.returncode != 0:
            return {"success": False, "error": "Wrapper script was not created successfully"}
        

        # Start the process using the wrapper script in background
        result = subprocess.run(['docker', 'exec', '-d', container_id, '/tmp/start_process.sh'], 
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            # Wait a moment and check if the process is actually running
            import time
            time.sleep(2)
            
            # Add a message to the live log stream to indicate process started
            from datetime import datetime
            live_log_streams[name].put(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] ===== PROCESS RESTART =====')
            live_log_streams[name].put(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] Process start initiated')
            
            # Check if process started successfully
            status_check = check_process_running_in_container(name)
            
            if status_check.get('process_running'):
                live_log_streams[name].put(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] Process started successfully')
                return {"success": True, "message": "Process started successfully"}
            else:
                # Process failed to start or crashed immediately
                live_log_streams[name].put(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] Process failed to start or crashed')
                # Get recent logs to see what went wrong
                log_result = subprocess.run(['docker', 'exec', container_id, 'sh', '-c', f'tail -10 {log_file} 2>/dev/null || echo "No logs found"'], 
                                          capture_output=True, text=True)
                for line in log_result.stdout.split('\n'):
                    if line.strip():
                        live_log_streams[name].put(line.strip())
                return {"success": False, "error": f"Process started but crashed immediately. Check logs for details."}
        else:
            from datetime import datetime
            live_log_streams[name].put(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] Failed to start process: {result.stderr}')
            return {"success": False, "error": f"Failed to start process: {result.stderr}"}

    except subprocess.CalledProcessError as e:
        return {"success": False, "error": f"Failed to start process: {e.stderr}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    
def kill_process_tree(pid, inside_container=False, container_id=None):
    """
    Kill a process and all its children.
    If inside_container is True, kill processes inside the specified container using docker exec.
    Otherwise, kill processes on the host (use with caution).
    """
    if inside_container and container_id:
        try:
            # Get child PIDs inside the container
            ps_result = subprocess.run([
                'docker', 'exec', container_id, 'ps', '-o', 'pid,ppid', '--no-headers'
            ], capture_output=True, text=True)
            if ps_result.returncode != 0:
                return {"success": False, "message": "Failed to get process tree inside container."}
            pid_map = {}
            for line in ps_result.stdout.split('\n'):
                parts = line.split()
                if len(parts) == 2:
                    pid_map[parts[0]] = parts[1]
            # Find all children recursively
            def get_children(target_pid):
                children = [p for p, parent in pid_map.items() if parent == target_pid]
                all_children = []
                for child in children:
                    all_children.append(child)
                    all_children.extend(get_children(child))
                return all_children
            all_pids = [pid] + get_children(pid)
            # Kill all processes inside the container
            for p in all_pids:
                subprocess.run(['docker', 'exec', container_id, 'kill', '-TERM', p], capture_output=True, text=True)
            return {"success": True, "message": f"Killed process tree for PID {pid} inside container."}
        except Exception as e:
            return {"success": False, "message": f"Failed to kill process tree inside container: {e}"}
    else:
        # Host process tree kill (use with caution)
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                child.kill()
            parent.kill()
            return {"success": True, "message": f"Process tree for PID {pid} killed on host."}
        except Exception as e:
            return {"success": False, "message": f"Failed to kill process tree: {e}"}

def stop_process_in_container(name):
    """Stop the main process inside the container without stopping the container"""
    try:
        process_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
        os.chdir(process_dir)

        # Get container ID
        result = subprocess.run(['docker-compose', 'ps', '-q', name], capture_output=True, text=True, check=True)
        container_id = result.stdout.strip()

        if not container_id:
            return {"success": True, "message": "Container not running"}

        # Get the main command from environment
        result = subprocess.run(['docker', 'inspect', '--format', '{{range .Config.Env}}{{println .}}{{end}}', container_id],
                              capture_output=True, text=True)
        
        main_command = None
        for line in result.stdout.split('\n'):
            if line.startswith('MAIN_COMMAND='):
                main_command = line.split('=', 1)[1].strip('"')
                break

        if not main_command:
            return {"success": False, "error": "No MAIN_COMMAND found in container environment"}

        # Get the process port for additional cleanup
        process = find_process_by_name(name)
        process_port = None
        if process and hasattr(process, 'port_id') and process.port_id:
            process_port = 8000 + process.port_id

        # Kill processes matching the main command
        command_parts = main_command.split()
        
        # Get process list
        result = subprocess.run(['docker', 'exec', container_id, 'ps', 'aux'], 
                              capture_output=True, text=True)
        
        if result.returncode != 0:
            return {"success": False, "error": "Failed to get process list"}

        # Find and kill matching processes (including zombie cleanup)
        processes_killed = 0
        processes_to_kill = []
        zombie_processes = []
        port_processes = []
        
        for line in result.stdout.split('\n')[1:]:  # Skip header
            if line.strip():
                # Extract PID (second column)
                parts = line.split()
                if len(parts) >= 2:
                    pid = parts[1]
                    # Check if this process matches our command
                    if any(part in line for part in command_parts if len(part) > 2):
                        if '<defunct>' in line or ' Z ' in line:
                            zombie_processes.append((pid, line.strip()))
                        else:
                            processes_to_kill.append((pid, line.strip()))

        # Also check for processes listening on the process port
        if process_port:
            try:
                # Check for processes listening on the port using netstat
                netstat_result = subprocess.run(['docker', 'exec', container_id, 'netstat', '-tlnp'], 
                                              capture_output=True, text=True)
                if netstat_result.returncode == 0:
                    for line in netstat_result.stdout.split('\n'):
                        if f':{process_port}' in line and 'LISTEN' in line:
                            # Extract PID from netstat output (format: pid/program_name)
                            parts = line.split()
                            if len(parts) >= 7:
                                pid_program = parts[6]
                                if '/' in pid_program:
                                    port_pid = pid_program.split('/')[0]
                                    if port_pid.isdigit() and port_pid not in [p[0] for p in processes_to_kill]:
                                        port_processes.append((port_pid, f"Process listening on port {process_port}"))
                else:
                    # Fallback: try using lsof if netstat fails
                    lsof_result = subprocess.run(['docker', 'exec', container_id, 'lsof', '-ti', f':{process_port}'], 
                                               capture_output=True, text=True)
                    if lsof_result.returncode == 0:
                        for pid in lsof_result.stdout.strip().split('\n'):
                            if pid.strip() and pid.strip().isdigit():
                                if pid.strip() not in [p[0] for p in processes_to_kill]:
                                    port_processes.append((pid.strip(), f"Process listening on port {process_port}"))
            except Exception:
                pass

        # Also check for processes listening on the process port (host OS)
        if process_port:
            try:
                # Use netstat to find host processes listening on the port
                netstat_result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
                if netstat_result.returncode == 0:
                    for line in netstat_result.stdout.split('\n'):
                        if f':{process_port} ' in line and 'LISTENING' in line:
                            parts = line.split()
                            if len(parts) >= 5:
                                host_pid = parts[-1]
                                if host_pid.isdigit():
                                    # Try to kill the process
                                    subprocess.run(['taskkill', '/PID', host_pid, '/F'], capture_output=True, text=True)
            except Exception:
                pass

        # Kill active processes first
        all_processes_to_kill = processes_to_kill + port_processes
        for pid, process_description in all_processes_to_kill:
            kill_result = kill_process_tree(pid, inside_container=True, container_id=container_id)
            if kill_result.get("success"):
                processes_killed += 1

        # Clean up zombie processes (they're already dead, just need parent to reap them)
        if zombie_processes:
            # Try to find and signal their parent processes
            for zombie_pid, zombie_line in zombie_processes:
                # Zombies are already dead, they just need to be reaped by parent
                # Let's try to get their parent PID and signal it
                ppid_result = subprocess.run(['docker', 'exec', container_id, 'ps', '-o', 'pid,ppid', '--no-headers'], 
                                           capture_output=True, text=True)
                if ppid_result.returncode == 0:
                    for line in ppid_result.stdout.split('\n'):
                        if line.strip() and zombie_pid in line.split():
                            parts = line.split()
                            if len(parts) >= 2 and parts[0] == zombie_pid:
                                parent_pid = parts[1]
                                # Send SIGCHLD to parent to force reaping
                                subprocess.run(['docker', 'exec', container_id, 'kill', '-CHLD', parent_pid], 
                                             capture_output=True, text=True)

        if processes_killed > 0 or zombie_processes:
            message = f"Stopped {processes_killed} process(es)"
            if len(port_processes) > 0:
                message += f" (including {len(port_processes)} port-listening process(es))"
            if zombie_processes:
                message += f" and cleaned {len(zombie_processes)} zombie process(es)"
            return {"success": True, "message": message}
        else:
            return {"success": True, "message": "No matching processes found to stop"}

    except subprocess.CalledProcessError as e:
        return {"success": False, "error": f"Failed to stop process: {e.stderr}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def is_always_running_container(name):
    """Check if this is an always-running container (has MAIN_COMMAND environment variable)"""
    try:
        process_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
        os.chdir(process_dir)

        # Get container ID
        result = subprocess.run(['docker-compose', 'ps', '-q', name], capture_output=True, text=True, check=True)
        container_id = result.stdout.strip()

        if not container_id:
            return False

        # Check for MAIN_COMMAND in environment
        result = subprocess.run(['docker', 'inspect', '--format', '{{range .Config.Env}}{{println .}}{{end}}', container_id],
                              capture_output=True, text=True)
        
        for line in result.stdout.split('\n'):
            if line.startswith('MAIN_COMMAND='):
                return True
        
        return False

    except Exception:
        return False


def generate_reset_email_body(reset_url):
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Password Reset Request</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background-color: #f4f4f4;
                padding: 20px;
                margin: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            }}
            h1 {{
                color: #333;
                font-size: 24px;
                margin-bottom: 20px;
            }}
            p {{
                font-size: 16px;
                line-height: 1.5;
                color: #555;
            }}
            .btn {{
                display: inline-block;
                padding: 12px 25px;
                margin-top: 20px;
                background-color: #007bff;
                color: #ffffff;
                text-decoration: none;
                border-radius: 5px;
                font-weight: bold;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Password Reset Request</h1>
            <p>Hello,</p>
            <p>We received a request to reset your password. You can reset your password by clicking the button below:</p>
            <a href="{reset_url}" class="btn">Reset Your Password</a>
            <p>If you did not request a password reset, you can ignore this email.</p>
            <p>Best regards,<br>Your Support Team</p>
        </div>
    </body>
    </html>
    """


def execute_handler(handler_type, function_name, *args, **kwargs):
    try:
        module_name = f"handlers.{handler_type}"
        module = importlib.import_module(module_name)
        function = getattr(module, function_name)
        return function(*args, **kwargs)
    except ModuleNotFoundError:
        raise ImportError(f"Handler '{handler_type}' not found.") from None
    except AttributeError:
        raise AttributeError(f"Function '{function_name}' not found in '{handler_type}'.") from None
    

handlers_folder = os.path.join(os.getcwd(), 'handlers')


def find_types():
    types = []
    
    for _root, _dirs, files in os.walk(handlers_folder):
        for filename in files:
            
            if filename.endswith('.py') and filename not in types:
                types.append(filename.split('.')[0])
    
    return types


def _send_command_to_minecraft_console(container_id, process_name, command, timeout):
    """Send a command to a Minecraft JVM by streaming into the server's STDIN."""
    sanitized_command = command.rstrip('\n') + '\n'
    encoded_command = base64.b64encode(sanitized_command.encode('utf-8')).decode('ascii')

    shell_script = textwrap.dedent(
        f"""
        MC_PID=$(ps -eo pid,command | grep -E 'fabric-server-launch.jar|minecraft_server.jar|server.jar' | grep -v grep | head -n 1 | awk '{{print $1}}')
        if [ -z "$MC_PID" ]; then
            MC_PID=$(pgrep -af 'java' | head -n 1 | awk '{{print $1}}')
        fi
        if [ -z "$MC_PID" ]; then
            echo "Minecraft JVM process not found" >&2
            exit 44
        fi
        echo '{encoded_command}' | base64 -d | tee /proc/$MC_PID/fd/0 > /dev/null
        """
    )

    result = subprocess.run(
        ['docker', 'exec', container_id, '/bin/sh', '-c', shell_script],
        capture_output=True,
        text=True,
        timeout=timeout
    )

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if result.returncode == 0:
        live_log_streams[process_name].put(f'[{timestamp}] Command delivered to Minecraft JVM')
        return {
            "success": True,
            "stdout": "Command forwarded to Minecraft server console",
            "stderr": "",
            "return_code": 0
        }

    error_message = result.stderr.strip() or "Failed to forward command to Minecraft server"
    live_log_streams[process_name].put(f'[{timestamp}] [ERROR] {error_message}')
    return {
        "success": False,
        "error": error_message,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "return_code": result.returncode
    }


def execute_command_in_container(name, command, working_dir="/app", timeout=30):
    """Execute a command inside the container and return the result"""
    try:
        process_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
        os.chdir(process_dir)

        # Get container ID
        result = subprocess.run(['docker-compose', 'ps', '-q', name], capture_output=True, text=True, check=True)
        container_id = result.stdout.strip()

        if not container_id:
            return {"success": False, "error": "Container is not running"}

        # Check if container is actually running
        result = subprocess.run(['docker', 'inspect', '--format', '{{.State.Status}}', container_id], 
                              capture_output=True, text=True)
        
        if result.returncode != 0 or result.stdout.strip() != 'running':
            return {"success": False, "error": "Container is not in running state"}

        # Check if this is a Minecraft server by checking the process type in database
        process = find_process_by_name(name)
        is_minecraft = process and process.type == 'minecraft'

        # For Minecraft servers, feed STDIN directly (mirrors how Pterodactyl streams commands)
        if is_minecraft:
            live_log_streams[name].put(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] $ {command}')
            return _send_command_to_minecraft_console(container_id, name, command, timeout)

        # For non-Minecraft containers, use the original approach
        # Execute the command inside the container
        log_file = f"/tmp/{name}_process.log"
        full_command = (
            f"cd {working_dir} && "
            f"echo \"[$(date -u +'%Y-%m-%d %H:%M:%S')] $ {command}\" >> {log_file} && "
            f"{command} 2>&1 | while IFS= read -r line; do "
            f"echo \"[$(date -u +'%Y-%m-%d %H:%M:%S')] $line\" >> {log_file}; "
            f"done"
        )
        result = subprocess.run(['docker', 'exec', container_id, 'sh', '-c', full_command], 
                              capture_output=True, text=True, timeout=timeout)
        
        if result.returncode == 0:
            return {
                "success": True, 
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode
            }
        else:
            # Do NOT log error to the persistent log file, only stream it with timestamp
            return {
                "success": False,
                "error": f"Command failed with return code {result.returncode}",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode
            }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Command timed out after {timeout} seconds"}
    except subprocess.CalledProcessError as e:
        return {"success": False, "error": f"Failed to execute command: {e.stderr}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def execute_interactive_command_in_container(name, command, working_dir="/app"):
    """Execute an interactive command inside the container (returns process handle for real-time interaction)"""
    try:
        process_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
        os.chdir(process_dir)

        # Get container ID
        result = subprocess.run(['docker-compose', 'ps', '-q', name], capture_output=True, text=True, check=True)
        container_id = result.stdout.strip()

        if not container_id:
            return {"success": False, "error": "Container is not running", "process": None}

        # Check if container is actually running
        result = subprocess.run(['docker', 'inspect', '--format', '{{.State.Status}}', container_id], 
                              capture_output=True, text=True)
        
        if result.returncode != 0 or result.stdout.strip() != 'running':
            return {"success": False, "error": "Container is not in running state", "process": None}

        # Start the interactive command
        full_command = f"cd {working_dir} && {command}"
        
        # Start the process in interactive mode
        process = subprocess.Popen(
            ['docker', 'exec', '-it', container_id, 'sh', '-c', full_command],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        
        return {
            "success": True,
            "process": process,
            "message": "Interactive command started successfully"
        }

    except subprocess.CalledProcessError as e:
        return {"success": False, "error": f"Failed to start interactive command: {e.stderr}", "process": None}
    except Exception as e:
        return {"success": False, "error": str(e), "process": None}


# ==================== Domain Validation and DNS Health Check Functions ====================

def validate_domain_format(domain):
    """
    Validate domain format with comprehensive checks.
    Returns dict with 'valid' (bool), 'error' (str if invalid), and 'normalized' (str if valid)
    """
    if not domain or not isinstance(domain, str):
        return {"valid": False, "error": "Domain cannot be empty"}
    
    # Strip whitespace
    domain = domain.strip()
    
    # Check length (253 chars max for full domain, 63 per label)
    if len(domain) > 253:
        return {"valid": False, "error": "Domain name is too long (max 253 characters)"}
    
    # Convert to lowercase for consistency
    domain = domain.lower()
    
    # Support wildcard domains for SSL
    is_wildcard = domain.startswith('*.')
    if is_wildcard:
        domain = domain[2:]  # Remove wildcard for validation
    
    # Check if domain is empty after removing wildcard
    if not domain:
        return {"valid": False, "error": "Invalid wildcard domain"}
    
    # Basic regex pattern for domain validation
    # Allows: alphanumeric, hyphens, dots, and IDN (internationalized domain names)
    domain_pattern = re.compile(
        r'^(?:[a-z0-9\u00a1-\uffff](?:[a-z0-9\u00a1-\uffff-]{0,61}[a-z0-9\u00a1-\uffff])?\.)*'
        r'(?:[a-z0-9\u00a1-\uffff](?:[a-z0-9\u00a1-\uffff-]{0,61}[a-z0-9\u00a1-\uffff])?)$',
        re.IGNORECASE
    )
    
    if not domain_pattern.match(domain):
        return {"valid": False, "error": "Invalid domain format. Use only letters, numbers, hyphens, and dots"}
    
    # Check for consecutive dots
    if '..' in domain:
        return {"valid": False, "error": "Domain cannot contain consecutive dots"}
    
    # Check if starts or ends with hyphen or dot
    if domain.startswith('-') or domain.endswith('-') or domain.startswith('.') or domain.endswith('.'):
        return {"valid": False, "error": "Domain cannot start or end with hyphen or dot"}
    
    # Split into labels and validate each
    labels = domain.split('.')
    
    # Need at least 2 labels (domain.tld) unless it's localhost
    if len(labels) < 2 and domain != 'localhost':
        return {"valid": False, "error": "Domain must have at least two parts (e.g., example.com)"}
    
    # Validate each label
    for label in labels:
        if not label:
            return {"valid": False, "error": "Domain contains empty label"}
        if len(label) > 63:
            return {"valid": False, "error": f"Label '{label}' is too long (max 63 characters)"}
        if label.startswith('-') or label.endswith('-'):
            return {"valid": False, "error": f"Label '{label}' cannot start or end with hyphen"}
    
    # Validate TLD (last label) - should be at least 2 characters and not all numeric
    tld = labels[-1]
    if len(tld) < 2 and domain != 'localhost':
        return {"valid": False, "error": "Top-level domain must be at least 2 characters"}
    
    # TLD should not be all numbers
    if tld.isdigit():
        return {"valid": False, "error": "Top-level domain cannot be all numbers"}
    
    # Common invalid patterns
    if domain in ['example.com', 'example.org', 'test.com', 'localhost.localdomain']:
        return {"valid": False, "error": "Please use a real domain name", "warning": True}
    
    # Return normalized domain (with wildcard if it was present)
    normalized = ('*.' + domain) if is_wildcard else domain
    return {"valid": True, "normalized": normalized}


def get_server_ip():
    """Get the server's public IP address"""
    try:
        # Try to get public IP from external service
        import urllib.request
        with urllib.request.urlopen('https://api.ipify.org?format=text', timeout=5) as response:
            public_ip = response.read().decode('utf-8').strip()
            return public_ip
    except Exception:
        pass
    
    # Fallback: get local network IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return None


def check_dns_health(domain, server_ip=None):
    """
    Check DNS health for a domain.
    Returns dict with 'status', 'records', 'points_to_server', 'warnings', 'errors'
    """
    if not domain:
        return {"status": "error", "error": "Domain is required"}
    
    # Validate domain format first
    validation = validate_domain_format(domain)
    if not validation.get("valid"):
        return {"status": "error", "error": validation.get("error")}
    
    domain = validation.get("normalized", domain).lstrip('*.')  # Remove wildcard for DNS check
    
    # Get server IP if not provided
    if not server_ip:
        server_ip = get_server_ip()
    
    result = {
        "status": "unknown",
        "domain": domain,
        "server_ip": server_ip,
        "records": {
            "A": [],
            "AAAA": [],
            "CNAME": []
        },
        "points_to_server": False,
        "warnings": [],
        "errors": []
    }
    
    resolver = dns.resolver.Resolver()
    resolver.timeout = 5
    resolver.lifetime = 5
    
    # Check A records (IPv4)
    try:
        answers = resolver.resolve(domain, 'A')
        for rdata in answers:
            ip_address = str(rdata)
            result["records"]["A"].append(ip_address)
            if server_ip and ip_address == server_ip:
                result["points_to_server"] = True
    except dns.resolver.NXDOMAIN:
        result["errors"].append("Domain does not exist (NXDOMAIN)")
        result["status"] = "error"
        return result
    except dns.resolver.NoAnswer:
        result["warnings"].append("No A records found")
    except dns.resolver.Timeout:
        result["errors"].append("DNS query timed out")
        result["status"] = "timeout"
        return result
    except Exception as e:
        result["warnings"].append(f"A record check failed: {str(e)}")
    
    # Check AAAA records (IPv6)
    try:
        answers = resolver.resolve(domain, 'AAAA')
        for rdata in answers:
            result["records"]["AAAA"].append(str(rdata))
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        pass  # AAAA records are optional
    except Exception:
        pass
    
    # Check CNAME records
    try:
        answers = resolver.resolve(domain, 'CNAME')
        for rdata in answers:
            result["records"]["CNAME"].append(str(rdata))
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        pass  # CNAME is optional
    except Exception:
        pass
    
    # Determine overall status
    if result["errors"]:
        result["status"] = "error"
    elif result["points_to_server"]:
        result["status"] = "healthy"
    elif result["records"]["A"] or result["records"]["AAAA"]:
        result["status"] = "warning"
        result["warnings"].append(f"Domain points to {result['records']['A'][0] if result['records']['A'] else result['records']['AAAA'][0]}, not to this server ({server_ip})")
    else:
        result["status"] = "warning"
        result["warnings"].append("No DNS records found for domain")
    
    return result


def check_ssl_certificate(domain):
    """
    Check SSL certificate status and get expiration information.
    Returns dict with 'exists', 'valid', 'expiration_date', 'days_until_expiry', 'issuer', 'validation_type'
    """
    cert_path = f'/etc/letsencrypt/live/{domain}/fullchain.pem'
    
    result = {
        "exists": False,
        "valid": False,
        "domain": domain,
        "errors": []
    }
    
    # Check if certificate file exists
    if not os.path.exists(cert_path):
        result["errors"].append("Certificate file not found")
        return result
    
    result["exists"] = True
    
    try:
        # Read certificate using openssl
        cmd = ['openssl', 'x509', '-in', cert_path, '-noout', '-dates', '-issuer', '-subject']
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        output = proc.stdout
        
        # Parse expiration date
        for line in output.split('\n'):
            if line.startswith('notAfter='):
                date_str = line.replace('notAfter=', '').strip()
                # Parse date format: "Jan 1 00:00:00 2025 GMT"
                expiration_date = datetime.strptime(date_str, '%b %d %H:%M:%S %Y %Z')
                result["expiration_date"] = expiration_date.strftime('%Y-%m-%d %H:%M:%S')
                
                # Calculate days until expiry
                days_until_expiry = (expiration_date - datetime.now()).days
                result["days_until_expiry"] = days_until_expiry
                
                # Determine if valid
                if days_until_expiry > 0:
                    result["valid"] = True
                else:
                    result["valid"] = False
                    result["errors"].append(f"Certificate expired {abs(days_until_expiry)} days ago")
                
                # Add warning if expiring soon
                if 0 < days_until_expiry <= 30:
                    result["warning"] = f"Certificate expires in {days_until_expiry} days"
            
            elif line.startswith('notBefore='):
                date_str = line.replace('notBefore=', '').strip()
                issued_date = datetime.strptime(date_str, '%b %d %H:%M:%S %Y %Z')
                result["issued_date"] = issued_date.strftime('%Y-%m-%d')
            
            elif line.startswith('issuer='):
                issuer = line.replace('issuer=', '').strip()
                result["issuer"] = issuer
                
                # Determine validation type based on issuer
                if "Let's Encrypt" in issuer or "LE" in issuer:
                    result["validation_type"] = "DV"  # Domain Validation
                    result["issuer_name"] = "Let's Encrypt"
                elif "DigiCert" in issuer or "GlobalSign" in issuer or "Comodo" in issuer:
                    result["validation_type"] = "OV/EV"  # Could be Organization or Extended Validation
                    result["issuer_name"] = issuer.split('CN=')[1].split(',')[0] if 'CN=' in issuer else "Unknown"
                else:
                    result["validation_type"] = "Unknown"
                    result["issuer_name"] = "Unknown"
        
        # Check if certificate is for wildcard domain
        cmd_check_cn = ['openssl', 'x509', '-in', cert_path, '-noout', '-text']
        proc_cn = subprocess.run(cmd_check_cn, capture_output=True, text=True, check=True)
        
        if '*.%s' % domain in proc_cn.stdout or '*.' in proc_cn.stdout:
            result["is_wildcard"] = True
        else:
            result["is_wildcard"] = False
        
    except subprocess.CalledProcessError as e:
        result["errors"].append(f"Failed to read certificate: {e.stderr}")
    except Exception as e:
        result["errors"].append(f"Error checking certificate: {str(e)}")
    
    return result


def check_domain_uniqueness(domain, current_process_name=None):
    """
    Check if domain is already used by another process.
    Returns dict with 'unique', 'conflicts' (list of process names using the domain)
    """
    if not domain:
        return {"unique": True, "conflicts": []}
    
    with current_app.app_context():
        from models.process import Process
        
        # Query all processes with this domain
        processes = Process.query.filter(Process.domain == domain).all()
        
        # Filter out current process if specified
        conflicts = [p.name for p in processes if p.name != current_process_name]
        
        return {
            "unique": len(conflicts) == 0,
            "conflicts": conflicts
        }


def get_domain_status(domain, process_name=None):
    """
    Get comprehensive domain status including validation, DNS health, SSL status, and uniqueness.
    This is the main function to call for complete domain status.
    """
    if not domain:
        return {"status": "empty", "error": "No domain configured"}
    
    result = {
        "domain": domain,
        "validation": None,
        "dns": None,
        "ssl": None,
        "uniqueness": None,
        "overall_status": "unknown"
    }
    
    # 1. Validate domain format
    validation = validate_domain_format(domain)
    result["validation"] = validation
    
    if not validation.get("valid"):
        result["overall_status"] = "invalid"
        return result
    
    normalized_domain = validation.get("normalized", domain)
    
    # 2. Check domain uniqueness
    uniqueness = check_domain_uniqueness(normalized_domain, process_name)
    result["uniqueness"] = uniqueness
    
    # 3. Check DNS health
    dns_status = check_dns_health(normalized_domain)
    result["dns"] = dns_status
    
    # 4. Check SSL certificate (skip for wildcard domains in DNS)
    check_domain = normalized_domain.lstrip('*.')
    ssl_status = check_ssl_certificate(check_domain)
    result["ssl"] = ssl_status
    
    # Determine overall status
    if not validation.get("valid"):
        result["overall_status"] = "invalid"
    elif not uniqueness.get("unique"):
        result["overall_status"] = "conflict"
    elif dns_status.get("status") == "error":
        result["overall_status"] = "dns_error"
    elif dns_status.get("status") == "warning":
        result["overall_status"] = "dns_warning"
    elif ssl_status.get("exists") and ssl_status.get("valid"):
        result["overall_status"] = "healthy"
    elif ssl_status.get("exists") and not ssl_status.get("valid"):
        result["overall_status"] = "ssl_expired"
    elif dns_status.get("points_to_server"):
        result["overall_status"] = "no_ssl"
    else:
        result["overall_status"] = "needs_configuration"
    
    return result
