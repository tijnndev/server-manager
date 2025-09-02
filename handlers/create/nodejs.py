from classes.result import Result
import json
import os


def create_docker_file(_process, dockerfile_path):
    try:
        directory = os.path.dirname(dockerfile_path)
        package_json_path = os.path.join(directory, 'package.json')

        package_json_content = json.dumps({
            "name": "my-app",
            "version": "1.0.0",
            "scripts": {
                "start": "node app.js"
            },
            "dependencies": {}
        }, indent=4)

        with open(package_json_path, "w") as f:
            f.write(package_json_content)
        
        dockerfile_content = """FROM node:latest
WORKDIR /app
COPY . /app
RUN npm i
CMD ["sh", "-c", "$COMMAND"]
"""
        with open(dockerfile_path, "w") as f:
            f.write(dockerfile_content)

        return Result(success=True, message="package.json and Dockerfile created successfully")
    
    except Exception as e:
        return Result(success=False, message=str(e))


def create_docker_compose_file(process, compose_file_path):
    try:
        with open(compose_file_path, 'w') as f:
            f.write(f"""services:
    {process.name}:
        build:
            context: .
            dockerfile: Dockerfile
        volumes:
            - .:/app
        # Always keep container running - process will be controlled via docker exec
        command: ["tail", "-f", "/dev/null"]
        ports:
            - "{process.port}:{process.port}"
        environment:
            - MAIN_COMMAND={json.dumps(process.command)}
        restart: unless-stopped
        stdin_open: true
        tty: true
""")
        return Result(success=True, message="Docker Compose file created successfully")
    except Exception as e:
        return Result(success=False, message=str(e))
