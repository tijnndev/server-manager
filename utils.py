from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import smtplib
from flask import current_app
import os
import subprocess
import random
import string
import importlib
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
            'minecraft': ['java'],
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
        
        # Look for the main command in the process list (exclude zombie processes)
        process_running = False
        matching_processes = []
        for line in processes.split('\n')[1:]:  # Skip header
            if line.strip():
                # Check if this is a zombie process (contains <defunct> or Z state)
                if '<defunct>' in line or ' Z ' in line:
                    continue
                    
                # Check if any search term appears in the process line
                if any(term in line for term in search_terms):
                    process_running = True
                    matching_processes.append(line.strip())

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
        stop_result = stop_process_in_container(name)

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
        script_content = wrapper_script.encode('utf-8')
        
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
    
import psutil
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

        # Check if this is a Minecraft server
        is_minecraft = False
        minecraft_workdir = "/server"  # Default Minecraft working directory
        env_result = subprocess.run(['docker', 'inspect', '--format', '{{range .Config.Env}}{{println .}}{{end}}', container_id],
                                   capture_output=True, text=True)
        print(env_result.stdout)
        if env_result.returncode == 0:
            for line in env_result.stdout.split('\n'):
                if line.startswith('MINECRAFT_SERVER='):
                    is_minecraft = True
                    break
        
        print(is_minecraft)        

        # For Minecraft servers, send command directly to the running Java process via stdin
        if is_minecraft:
            # Use docker attach with stdin to send the command
            # We need to send the command followed by a newline to the container's main process
            try:
                # Use docker exec to attach to the running process and send the command
                # First, log the command
                log_file = f"/tmp/{name}_process.log"
                subprocess.run(['docker', 'exec', container_id, 'sh', '-c', 
                               f'cd {minecraft_workdir} && echo "[$(date -u +\'%Y-%m-%d %H:%M:%S\')] $ {command}" >> {log_file}'],
                              capture_output=True, text=True, timeout=5)
                
                # Now send the command to the Minecraft server console using a named pipe approach
                # This approach writes to the stdin of the main Java process
                pipe_command = f'''
                    cd {minecraft_workdir}
                    PID=$(pgrep -f "java.*fabric-server-launch.jar")
                    if [ -n "$PID" ]; then
                        echo "{command}" | tee -a {log_file} > /proc/$PID/fd/0 2>&1
                        echo "[$(date -u +'%Y-%m-%d %H:%M:%S')] Command sent to Minecraft server" >> {log_file}
                    else
                        echo "[$(date -u +'%Y-%m-%d %H:%M:%S')] ERROR: Minecraft server process not found" >> {log_file}
                        exit 1
                    fi
                '''
                result = subprocess.run(['docker', 'exec', container_id, 'sh', '-c', pipe_command],
                                      capture_output=True, text=True, timeout=timeout)
                
                print(result.stdout)
                if result.returncode == 0:
                    # Add success message to log
                    live_log_streams[name].put(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] $ {command}')
                    live_log_streams[name].put(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] Command sent to Minecraft server successfully')
                    return {
                        "success": True,
                        "stdout": "Command sent to Minecraft server",
                        "stderr": "",
                        "return_code": 0
                    }
                else:
                    live_log_streams[name].put(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] [ERROR] Failed to send command to Minecraft server')
                    return {
                        "success": False,
                        "error": "Failed to send command to Minecraft server process",
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "return_code": result.returncode
                    }
            except Exception as e:
                return {"success": False, "error": f"Failed to send command to Minecraft server: {str(e)}"}

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
