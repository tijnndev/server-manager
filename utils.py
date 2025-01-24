from flask import jsonify, current_app
import os, subprocess, docker
from docker.errors import NotFound
from models.process import Process


client = docker.from_env()

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))
ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, 'active-servers')

def get_service_status(name):
    service = find_process_by_name(name)
    if not service:
        return jsonify({"error": "Service not found"}), 404

    try:
        service_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
        os.chdir(service_dir)

        result = subprocess.run(['docker-compose', 'ps', '-q'], capture_output=True, text=True, check=True)

        container_id = result.stdout.strip()

        if not container_id:
            return jsonify({"service": name, "status": "Exited"})

        container = client.containers.get(container_id)

        status = None

        print(container.status)

        if(container.status != "running"):
            status = "Exited"
        else:
            status = "Running"

        # print(status)

        return jsonify({"service": name, "status": status})

    except subprocess.CalledProcessError as e:
        return jsonify({"error": f"Failed to get service status: {e.stderr}"}), 500
    except NotFound:
        return jsonify({"error": "Container not found."}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
def find_process_by_name(name):
    with current_app.app_context():
        return Process.query.filter_by(name=name).first()

def find_process_by_id(process_id):
    with current_app.app_context():
        return Process.query.get(process_id)
