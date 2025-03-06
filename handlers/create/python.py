from classes.result import Result
import json, os

def create_docker_file(process, dockerfile_path):
    try:
        directory = os.path.dirname(dockerfile_path)
        requirements_txt_path = os.path.join(directory, 'requirements.txt')

        dependencies = process.dependencies.split(",") if isinstance(process.dependencies, str) else process.dependencies
        dependencies = [dep.strip() for dep in dependencies]

        with open(requirements_txt_path, "w") as f:
            for dep in dependencies:
                f.write(f"{dep}\n")

        dockerfile_content = """FROM python:3.13
WORKDIR /app
COPY . /app
RUN pip install -r requirements.txt
CMD ["sh", "-c", "$COMMAND"]
"""
        with open(dockerfile_path, "w") as f:
            f.write(dockerfile_content)
        return Result(success=True, message="Dockerfile created successfully")
    except Exception as e:
        return Result(success=False, message=str(e))

def create_docker_compose_file(process, compose_file_path):
    try:
        with open(compose_file_path, 'w') as f:
            f.write(f"""version: '3.7'

services:
    {process.name}:
        build:
            context: .
            dockerfile: Dockerfile
        volumes:
            - .:/app
        command: ["sh", "-c", {json.dumps(process.command)}]
        ports:
            - "{8000 + process.port_id}:{8000 + process.port_id}"
        environment:
            - COMMAND={json.dumps(process.command)}""")
        
        return Result(success=True, message="Docker Compose file created successfully")
    except Exception as e:
        return Result(success=False, message=str(e))
