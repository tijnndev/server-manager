from classes.result import Result
import json

def create_docker_file(process, dockerfile_path):
    try:
        dockerfile_content = f"""FROM golang:latest
WORKDIR /app
COPY . /app
RUN go mod init {process.name}
RUN go mod tidy
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
      - GO_ENV=production
      - COMMAND={json.dumps(process.command)}""")
            
        return Result(success=True, message="Docker Compose file created successfully")
    except Exception as e:
        return Result(success=False, message=str(e))
