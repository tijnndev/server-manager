from flask import jsonify, current_app
import os, subprocess
from docker.errors import NotFound
from models.process import Process


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))
ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, 'active-servers')

def get_service_status(name):
    service = find_process_by_name(name)
    if not service:
        return {"error": "Service not found"}

    try:
        service_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
        os.chdir(service_dir)

        # Get the container ID using 'docker-compose ps -q' (quiet mode to only output the container ID)
        result = subprocess.run(['docker-compose', 'ps', '-q', name], capture_output=True, text=True, check=True)
        container_id = result.stdout.strip()

        if not container_id:
            return {"service": name, "status": "Exited"}

        # Get container's status using 'docker inspect' to retrieve its state
        result = subprocess.run(['docker', 'inspect', '--format', '{{.State.Status}}', container_id], capture_output=True, text=True)

        if result.returncode != 0:
            return {"error": "Failed to get service status from docker inspect."}

        # Retrieve the status and determine whether the container is running or exited
        container_status = result.stdout.strip()

        if container_status == 'running':
            return {"service": name, "status": "Running"}
        else:
            return {"service": name, "status": "Exited"}

    except subprocess.CalledProcessError as e:
        return {"error": f"Failed to get service status: {e.stderr}"}
    except Exception as e:
        return {"error": str(e)}

    
def find_process_by_name(name):
    with current_app.app_context():
        return Process.query.filter_by(name=name).first()

def find_process_by_id(process_id):
    with current_app.app_context():
        return Process.query.get(process_id)
