from classes.result import Result
import json


def create_docker_file(_process, dockerfile_path):
    try:
        dockerfile_content = """FROM nginx:alpine
WORKDIR /usr/share/nginx/html
COPY . /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
"""
        with open(dockerfile_path, "w") as f:
            f.write(dockerfile_content)

        return Result(success=True, message="Dockerfile for Nginx created successfully")
    
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
