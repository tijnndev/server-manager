from classes.result import Result
import json


def create_docker_file(_process, dockerfile_path):
    try:
        dockerfile_content = """# Stage 1: Build the Vite project
FROM node:18 AS build

WORKDIR /app

COPY package.json ./ 
RUN npm install

COPY . . 
RUN npm run build

# Stage 2: Serve using Apache
FROM httpd:alpine

RUN apk add --no-cache apache2-utils

# Copy the build output to the Apache document root
COPY --from=build /app/dist/ /usr/local/apache2/htdocs/

# Copy .htaccess files
COPY .htaccess /usr/local/apache2/htdocs/

# Enable Apache mod_rewrite
RUN echo "LoadModule rewrite_module modules/mod_rewrite.so" >> /usr/local/apache2/conf/httpd.conf

# Configure Apache to allow .htaccess overrides and grant access
RUN echo "<Directory /usr/local/apache2/htdocs>" >> /usr/local/apache2/conf/httpd.conf && \
    echo "  AllowOverride All" >> /usr/local/apache2/conf/httpd.conf && \
    echo "  Require all granted" >> /usr/local/apache2/conf/httpd.conf && \
    echo "</Directory>" >> /usr/local/apache2/conf/httpd.conf

# Set the server name to localhost
RUN echo "ServerName localhost" >> /usr/local/apache2/conf/httpd.conf

EXPOSE 80
"""
        with open(dockerfile_path, "w") as f:
            f.write(dockerfile_content)

        return Result(success=True, message="Dockerfile for Vite created successfully")
    
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
            - \"{process.port}:{process.port}\"
        environment:
            - MAIN_COMMAND={json.dumps(process.command)}
        restart: unless-stopped
        stdin_open: true
        tty: true
""")
        return Result(success=True, message="Docker Compose file created successfully")
    except Exception as e:
        return Result(success=False, message=str(e))
