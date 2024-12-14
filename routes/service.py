# app/routes/service_routes.py
from flask import Blueprint, jsonify, request
import subprocess, psutil
import json
import os

service_routes = Blueprint('service', __name__)

SERVICES_DIRECTORY = 'active-servers'
SERVICES_FILE = 'services.json'
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, 'active-servers')

def is_within_base_dir(path, base=ACTIVE_SERVERS_DIR):
    abs_base = os.path.abspath(base)
    abs_path = os.path.abspath(path)
    return os.path.commonpath([abs_base]) == os.path.commonpath([abs_base, abs_path])


def load_services():
    services = {}
    if not os.path.exists(SERVICES_DIRECTORY):
        return services
    
    for server_dir in os.listdir(SERVICES_DIRECTORY):
        server_path = os.path.join(SERVICES_DIRECTORY, server_dir)
        if os.path.isdir(server_path):
            service_name = server_dir
            service_type = "unknown"
            for filename in os.listdir(server_path):
                if filename.endswith('.py'):
                    service_type = "python"
                    break
                elif filename.endswith('.js'):
                    service_type = "javascript"
                    break

            services[service_name] = {
                "type": service_type,
                "command": f"python {server_path}/server.py" if service_type == "python" else f"node {server_path}/server.js",
                "status": "stopped"
            }
    return services

def save_services(services):
    with open(SERVICES_FILE, 'w') as f:
        json.dump(services, f, indent=4)

@service_routes.route('/', methods=['GET'])
def get_services():
    services = load_services()
    return jsonify(services)

@service_routes.route('/add', methods=['POST'])
def add_service():
    data = request.json
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

        service_type = data.get("type")
        if service_type == "nodejs":
            file_path = os.path.join(service_dir, "index.js")
            with open(file_path, "w") as f:
                f.write("// Entry point for Node.js service\n")
                f.write("console.log('Node.js service running');\n")
        elif service_type == "python":
            file_path = os.path.join(service_dir, "app.py")
            with open(file_path, "w") as f:
                f.write("# Entry point for Python service\n")
                f.write("if __name__ == '__main__':\n")
                f.write("    print('Python service running')\n")
    except OSError as e:
        return jsonify({"error": f"Failed to create service directory: {e}"}), 500

    services[service_name] = {
        "type": data.get("type"),
        "command": data.get("command"),
        "status": "stopped"
    }
    save_services(services)

    return jsonify({"message": "Service added", "directory": service_dir})

@service_routes.route('/<string:name>/start', methods=['POST'])
def start_service(name):
    services = load_services()
    if name not in services:
        return jsonify({"error": "Service not found"}), 404
    try:
        command = services[name]["command"]
        process = subprocess.Popen(command.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        services[name]["status"] = "running"
        services[name]["pid"] = process.pid
        save_services(services)
        return jsonify({"message": f"Service {name} started", "pid": process.pid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@service_routes.route('/<string:name>/stop', methods=['POST'])
def stop_service(name):
    services = load_services()
    if name not in services or "pid" not in services[name]:
        return jsonify({"error": "Service not running"}), 400
    try:
        pid = services[name]["pid"]
        process = psutil.Process(pid)
        process.terminate()
        services[name]["status"] = "stopped"
        del services[name]["pid"]
        save_services(services)
        return jsonify({"message": f"Service {name} stopped"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
