from classes.result import Result
import os, json


def create_docker_file(process, dockerfile_path):
    try:
        dockerfile_content = """FROM nginx:alpine
WORKDIR /usr/share/nginx/html
COPY . /usr/share/nginx/html
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
            f.write(f"""version: '3.7'

services:
    {process.name}:
        build:
            context: .
            dockerfile: Dockerfile
        volumes:
            - .:/usr/share/nginx/html
        ports:
            - "{8000 + process.port_id}:80"
""")

        return Result(success=True, message="Docker Compose file for Nginx created successfully")
    
    except Exception as e:
        return Result(success=False, message=str(e))
