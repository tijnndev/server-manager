from classes.result import Result


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
            f.write(f"""version: '3.7'

services:
    mariadb:
        build:
            context: .
            dockerfile: Dockerfile
        environment:
            MYSQL_ROOT_PASSWORD: root_password
            MYSQL_DATABASE: my_database
            MYSQL_USER: my_user
            MYSQL_PASSWORD: my_password
        ports:
            - "{8000 + process.port_id}:3306"
        volumes:
            - mariadb-data:/var/lib/mysql
        networks:
            - mynetwork

volumes:
    mariadb-data:

networks:
    mynetwork:
        driver: bridge
""")

        return Result(success=True, message="Docker Compose file for MariaDB created successfully")
    
    except Exception as e:
        return Result(success=False, message=str(e))
