# app/routes/service_routes.py
from flask import Blueprint, jsonify, redirect, request, render_template, Response, current_app, url_for
import os, docker, json, re
from docker.errors import NotFound, APIError, BuildError, DockerException

from db import db
from models.process import Process

service_routes = Blueprint('service', __name__)
client = docker.from_env()

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

    processes = Process.query.all()

    for process in processes:
        try:
            services[process.name] = {
                "id": process.id,
                "type": process.type,
                "command": process.command,
                "file_location": process.file_location,
                "name": process.name,
                "status": process.get_status()
            }
        except NotFound:
            services[process.name] = {
                "id": process.id,
                "type": process.type,
                "command": process.command,
                "file_location": process.file_location,
                "name": process.name,
                "status": "Not Found"
            }
        except Exception as e:
            print(f"Error fetching status for {process.name}: {e}")
            services[process.name] = {
                "id": process.id,
                "type": process.type,
                "command": process.command,
                "file_location": process.file_location,
                "name": process.name,
                "status": "Error"
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
        command_list = data.get("command", "").split()
        db.session.add(new_process)
        db.session.commit()

        port_id = new_process.port_id

        port = 8000 + int(port_id)

        dependencies = data.get('dependencies')
        if dependencies:
            dependency_list = dependencies.split(',')
            requirements_path = os.path.join(service_dir, 'requirements.txt')
            with open(requirements_path, 'w') as f:
                for dep in dependency_list:
                    f.write(dep.strip() + '\n')

        service_type = data.get("type")
        if service_type == "nodejs":
            file_path = os.path.join(service_dir, "index.js")
            with open(file_path, "w") as f:
                f.write("// Entry point for Node.js service\n")
                f.write("console.log('Node.js service running');\n")

            dockerfile = f"""# DO NOT TOUCH THIS FILE
FROM node:latest
WORKDIR /app
COPY . /app
RUN npm init -y
CMD {command_list}
# DO NOT TOUCH THIS FILE"""
            dockerfile_path = os.path.join(service_dir, "Dockerfile")
            with open(dockerfile_path, "w") as f:
                f.write(dockerfile)

        elif service_type == "python":
            file_path = os.path.join(service_dir, "app.py")
            with open(file_path, "w") as f:
                f.write("# Entry point for Python service\n")
                f.write("if __name__ == '__main__':\n")
                f.write("    print('Python service running')\n")

            dockerfile = f"""# DO NOT TOUCH THIS FILE
FROM python:3.9-slim
WORKDIR /app
COPY . /app
RUN pip install -r requirements.txt
EXPOSE {port}
CMD {command_list}
# DO NOT TOUCH THIS FILE"""
            dockerfile_path = os.path.join(service_dir, "Dockerfile")
            with open(dockerfile_path, "w") as f:
                f.write(dockerfile)

        else:
            return jsonify({"error": "Unknown service type"}), 400

        image_tag = f"{service_name}_image"
        try:
            print(f"Building Docker image for {service_type}")
            client.images.build(path=service_dir, tag=image_tag, nocache=True)

        except BuildError as e:
            print(f"Error building Docker image: {e}")
            return jsonify({"error": f"Failed to build Docker image: {e}"}), 500

        command = data.get("command")
        container_name = f"{service_type}_{service_name}"
        try:
            try:
                existing_container = client.containers.get(container_name)
                print(f"Removing existing container: {existing_container.id}")
                existing_container.remove(force=True)
            except NotFound:
                pass

            print("Creating and starting container")
            container = client.containers.run(
                image_tag,
                name=container_name,
                command=command,
                volumes={service_dir: {"bind": "/app", "mode": "rw"}},
                ports={str(port): port},
                detach=True
            ) # type: ignore

            print(f"Container started: {container.id}")

            new_process.id = container.id
            db.session.commit()

        except DockerException as e: # type: ignore
            print(f"Error starting Docker container: {e}")
            return jsonify({"error": f"Failed to create Docker container: {e}"}), 500

        except Exception as e:
            print(f"Unexpected error: {e}")
            return jsonify({"error": f"Unexpected error: {e}"}), 500

    except OSError as e:
        return jsonify({"error": f"Failed to create service directory: {e}"}), 500
    except DockerException as e:
        return jsonify({"error": f"Failed to create Docker container: {e}"}), 500

    return jsonify({"message": "Service added and running in Docker container", "directory": service_dir, "container_id": container.id, "port": port})


@service_routes.route('/start/<string:name>', methods=['POST'])
def start_service(name):
    service = find_process_by_name(name)
    print(service)
    container_name = f"{name}_container"
    image_tag = f"{name}_image"

    if not service:
        return jsonify({"error": "Service not found"}), 404

    try:
        try:
            existing_container = next(
                (c for c in client.containers.list(all=True) if c.name == container_name), None
            )
            if existing_container:
                print(f"Stopping and removing existing container: {container_name}")
                existing_container.stop()
                existing_container.remove(force=True)
        except Exception as e:
            print(f"Error removing old container: {e}")

        try:
            old_image = client.images.get(image_tag)
            client.images.remove(image=old_image.id, force=True)
            print(f"Old image {image_tag} removed.")
        except Exception as e:
            print(f"No existing image found for {image_tag}, skipping removal: {e}")

        service_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
        print(f"Building new Docker image for {name}...")
        client.images.build(path=service_dir, tag=image_tag, nocache=True)
        print(f"Docker image {image_tag} built successfully.")

        port_id = service.port_id
        port = 8000 + int(port_id)

        print(f"Creating and starting new container: {container_name}")
        container = client.containers.run(
            image=image_tag,
            name=container_name,
            detach=True,
            auto_remove=False,
            restart_policy={"Name": "always"},
            ports={str(port): port}
        )
        
        print(f"Updating process ID to {container.id}")
        service.update_id(str(container.id))

        return jsonify({
            "message": f"Service {name} started successfully with updated command.",
            "container_id": container.id
        })

    except BuildError as build_error:
        print(f"Build failed for {name}: {build_error}")
        return jsonify({"error": f"Failed to build image: {build_error}"}), 500
    except APIError as api_error:
        print(f"Docker API error: {api_error}")
        return jsonify({"error": f"Docker API error: {api_error}"}), 500
    except Exception as e:
        print(f"Unexpected error: {e}")
        return jsonify({"error": str(e)}), 500



@service_routes.route('/stop/<string:name>', methods=['POST'])
def stop_service(name):
    container_id = "Unkown"
    service = find_process_by_name(name)
    if not service:
        return jsonify({"error": "Service not found"}), 404

    try:
        container_id = service.id
        if not container_id:
            return jsonify({"error": "Service ID not found"}), 404

        container = client.containers.get(container_id)

        if container.status == 'running':
            container.stop()
            print(f"Service {name} stopped successfully.")
            return jsonify({"message": f"Service {name} stopped successfully."})
        else:
            print(f"Service {name} is not running.")
            return jsonify({"error": f"Service {name} is not running."}), 400

    except NotFound:
        return jsonify({"error": f"Container with ID {container_id} not found."}), 404
    except APIError as e:
        return jsonify({"error": f"Docker API error: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def find_process_by_name(name):
    with current_app.app_context():
        return Process.query.filter_by(name=name).first()

def find_process_by_id(process_id):
    with current_app.app_context():
        return Process.query.get(process_id)


@service_routes.route('/console/<string:name>', methods=['GET'])
def console(name):
    service = find_process_by_name(name)
    if not service:
        return jsonify({"error": "Service not found"}), 404
    
    return render_template('console.html', service=service)

@service_routes.route('/console/<string:name>/logs', methods=['GET'])
def stream_logs(name):
    service = find_process_by_name(name)
    if not service:
        return jsonify({"error": "Service not found"}), 404

    try:
        container = client.containers.get(service.id)
        logs = container.logs(stream=True, follow=True, tail=50)
        
        def colorize_log(log):
            log = log.decode('utf-8')
            
            log = re.sub(r'\033\[([0-9;]+)m', lambda match: f'<span style="color: {ansi_to_html(match.group(1))};">', log)
            log = log.replace('\033[0m', '</span>')
            
            return log
        
        def generate():
            for log in logs:
                yield f"data: {colorize_log(log)}\n\n"
        
        return Response(generate(), content_type='text/event-stream')
    except NotFound:
        return jsonify({"error": "Container not found"}), 404

@service_routes.route('/console/<string:name>/send', methods=['POST'])
def send_command(name):
    service = find_process_by_name(name)
    if not service or not request.json:
        return jsonify({"error": "Service not found"}), 404

    command = request.json.get('command')
    if not command:
        return jsonify({"error": "No command provided"}), 400

    try:
        container = client.containers.get(service.id)
        exec_id = container.exec_run(command, tty=True, stdin=True)
        return jsonify({"message": "Command executed", "output": exec_id.output.decode('utf-8')})
    except NotFound:
        return jsonify({"error": "Container not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
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

@service_routes.route('/settings/<name>', methods=['GET', 'POST'])
def settings(name):
    service = find_process_by_name(name)
    if not service:
        return render_template('settings.html', service=service)
    
    if request.method == 'POST':
        # Make sure the form has all the expected keys
        print(request.form)
        
        service.name = request.form.get('name')
        service.description = request.form.get('description')
        service.command = request.form.get('command')
        service.type = request.form.get('type')
        service.params = request.form.get('params', '')

        service_dir = os.path.join(ACTIVE_SERVERS_DIR, service.name)
        dockerfile_path = f'{service_dir}/Dockerfile'

        if os.path.exists(dockerfile_path):
            with open(dockerfile_path, 'r') as dockerfile:
                dockerfile_content = dockerfile.readlines()

            for idx, line in enumerate(dockerfile_content):
                if line.startswith("CMD") or line.startswith("ENTRYPOINT"):
                    dockerfile_content[idx] = f'CMD {service.command.split()}\n'
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
    
    return render_template('settings.html', service=service)
