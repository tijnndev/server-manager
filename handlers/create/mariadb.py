from classes.result import Result
import json

def create_docker_file(_process, dockerfile_path):
    try:
        dockerfile_content = """FROM mariadb:latest
ENV MYSQL_ROOT_PASSWORD=root_password
ENV MYSQL_DATABASE=my_database
ENV MYSQL_USER=my_user
ENV MYSQL_PASSWORD=my_password
EXPOSE 3306
"""
        with open(dockerfile_path, "w") as f:
            f.write(dockerfile_content)

        return Result(success=True, message="Dockerfile for MariaDB created successfully")
    
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
        command: [\"tail\", \"-f\", \"/dev/null\"]
        ports:
            - "{8000 + process.port_id}:3306"
        environment:
            - MAIN_COMMAND={json.dumps(process.command)}
        restart: unless-stopped
        stdin_open: true
        tty: true
""")
        return Result(success=True, message="Docker Compose file created successfully")
    except Exception as e:
        return Result(success=False, message=str(e))
