from classes.result import Result
import json

def create_docker_file(_process, dockerfile_path):
    try:
        dockerfile_content = """FROM php:apache
RUN apt-get update && apt-get install -y libpng-dev libjpeg-dev libfreetype6-dev \
    && docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-install gd pdo pdo_mysql mysqli

RUN a2enmod rewrite
WORKDIR /var/www/html
COPY . /var/www/html
EXPOSE 80
CMD ["apache2-foreground"]
"""
        with open(dockerfile_path, "w") as f:
            f.write(dockerfile_content)

        return Result(success=True, message="Dockerfile for PHP + Apache created successfully")
    
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
