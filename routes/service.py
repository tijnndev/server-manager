# app/routes/service_routes.py
from flask import Blueprint, jsonify, request
import subprocess, psutil
import json
import os

service_routes = Blueprint('service_routes', __name__)

SERVICES_DIRECTORY = 'active-servers'
SERVICES_FILE = 'services.json'

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

@service_routes.route('/api/services', methods=['GET'])
def get_services():
    services = load_services()
    return jsonify(services)

@service_routes.route('/api/services', methods=['POST'])
def add_service():
    data = request.json
    services = load_services()
    service_name = data.get("name")
    if not service_name or service_name in services:
        return jsonify({"error": "Invalid or duplicate service name"}), 400
    services[service_name] = {
        "type": data.get("type"),
        "command": data.get("command"),
        "status": "stopped"
    }
    save_services(services)
    return jsonify({"message": "Service added"})

@service_routes.route('/api/services/<string:name>/start', methods=['POST'])
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

@service_routes.route('/api/services/<string:name>/stop', methods=['POST'])
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
