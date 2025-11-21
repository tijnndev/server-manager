from classes.result import Result


def create_docker_file(process, dockerfile_path):
    try:
        dockerfile_content = f"""FROM eclipse-temurin:21-jre-jammy

WORKDIR /server

RUN apt-get update && \
    apt-get install -y wget jq unzip && \
    apt-get clean

COPY eula.txt .
COPY server.properties .

# Create startup script that installs Fabric on first run and logs output
RUN echo '#!/bin/bash' > /start.sh && \
    echo 'LOG_FILE=/tmp/minecraft_process.log' >> /start.sh && \
    echo 'touch $LOG_FILE' >> /start.sh && \
    echo 'if [ ! -f fabric-server-launch.jar ]; then' >> /start.sh && \
    echo '  echo "Installing Fabric server..." | tee -a $LOG_FILE' >> /start.sh && \
    echo '  LATEST_VERSION=$(wget -qO- https://meta.fabricmc.net/v2/versions/game | jq -r ".[0].version")' >> /start.sh && \
    echo '  INSTALLER_URL=$(wget -qO- https://meta.fabricmc.net/v2/versions/installer | jq -r ".[0].url")' >> /start.sh && \
    echo '  wget -O fabric-installer.jar "$INSTALLER_URL"' >> /start.sh && \
    echo '  java -jar fabric-installer.jar server -downloadMinecraft -mc-version "$LATEST_VERSION" 2>&1 | tee -a $LOG_FILE' >> /start.sh && \
    echo 'fi' >> /start.sh && \
    echo 'exec java -Xmx2G -Xms1G -jar fabric-server-launch.jar nogui 2>&1 | tee -a $LOG_FILE' >> /start.sh && \
    chmod +x /start.sh

# Set environment variable to mark this as a Minecraft server
ENV MINECRAFT_SERVER=true

EXPOSE {25565 + process.port_id}

CMD ["/start.sh"]
"""
        with open(dockerfile_path, "w") as f:
            f.write(dockerfile_content)
        
        return Result(success=True, message="Minecraft server files and Dockerfile created successfully")
    
    except Exception as e:
        return Result(success=False, message=str(e))


def create_docker_compose_file(process, compose_file_path):
    try:
        # Get the directory where the compose file will be created
        import os
        compose_dir = os.path.dirname(compose_file_path)
        
        # Create eula.txt file
        eula_path = os.path.join(compose_dir, 'eula.txt')
        with open(eula_path, 'w') as f:
            f.write('eula=true\n')
        
        # Create server.properties file with basic settings
        properties_path = os.path.join(compose_dir, 'server.properties')
        with open(properties_path, 'w') as f:
            f.write(f"""# Minecraft server properties
server-port={25565 + process.port_id}
enable-rcon=false
gamemode=survival
difficulty=easy
max-players=20
online-mode=true
white-list=false
motd=A Minecraft Server
""")
        
        with open(compose_file_path, 'w') as f:
            f.write(f"""services:
    {process.name}:
        build:
            context: .
            dockerfile: Dockerfile
        ports:
            - "{25565 + process.port_id}:{25565 + process.port_id}"
        volumes:
            - ./server-data:/server
        restart: unless-stopped
        stdin_open: true
        tty: true
        mem_limit: 3g
""")
        return Result(success=True, message="Docker Compose file and server files created successfully")
    except Exception as e:
        return Result(success=False, message=str(e))
