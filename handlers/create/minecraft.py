from classes.result import Result
import json
import os


def create_docker_file(process, dockerfile_path):
    try:
        directory = os.path.dirname(dockerfile_path)
        
        # Create eula.txt file (required for Minecraft servers)
        eula_path = os.path.join(directory, 'eula.txt')
        with open(eula_path, "w") as f:
            f.write("eula=true\n")
        
        # Create server.properties with default configuration
        server_properties_path = os.path.join(directory, 'server.properties')
        with open(server_properties_path, "w") as f:
            f.write(f"""# Minecraft server properties
server-port={25565 + process.port_id}
max-players=20
motd=A Minecraft Server
gamemode=survival
difficulty=normal
pvp=true
enable-command-block=false
spawn-protection=16
max-world-size=29999984
online-mode=true
allow-nether=true
allow-flight=false
view-distance=10
""")
        
        # Create download script
        download_script_path = os.path.join(directory, 'download-server.sh')
        with open(download_script_path, "w") as f:
            f.write("""#!/bin/bash
set -e

if [ ! -f server.jar ]; then
    echo "Downloading Minecraft server..."
    LATEST_VERSION=$(wget -qO- https://launchermeta.mojang.com/mc/game/version_manifest.json | jq -r '.latest.release')
    echo "Latest Minecraft version: $LATEST_VERSION"
    
    SERVER_URL=$(wget -qO- https://launchermeta.mojang.com/mc/game/version_manifest.json | jq -r ".versions[] | select(.id == \\"$LATEST_VERSION\\") | .url")
    echo "Fetching version manifest from: $SERVER_URL"
    
    DOWNLOAD_URL=$(wget -qO- "$SERVER_URL" | jq -r '.downloads.server.url')
    echo "Downloading server from: $DOWNLOAD_URL"
    
    wget -O server.jar "$DOWNLOAD_URL"
    echo "Download complete!"
else
    echo "Server JAR already exists, skipping download."
fi
""")
        
        dockerfile_content = """FROM eclipse-temurin:21-jre-jammy

WORKDIR /server

# Install wget and jq
RUN apt-get update && apt-get install -y wget jq && apt-get clean

# Download latest Minecraft Vanilla server
RUN LATEST_VERSION=$(wget -qO- https://launchermeta.mojang.com/mc/game/version_manifest.json | jq -r '.latest.release') && \
    SERVER_URL=$(wget -qO- https://launchermeta.mojang.com/mc/game/version_manifest.json | jq -r ".versions[] | select(.id == \"$LATEST_VERSION\") | .url") && \
    DOWNLOAD_URL=$(wget -qO- "$SERVER_URL" | jq -r '.downloads.server.url') && \
    wget -O server.jar "$DOWNLOAD_URL"

# Accept EULA
RUN echo "eula=true" > eula.txt

# Expose default Minecraft port
EXPOSE 25565

# Start the server
CMD ["java", "-Xmx2G", "-Xms1G", "-jar", "server.jar", "nogui"]
"""
        with open(dockerfile_path, "w") as f:
            f.write(dockerfile_content)
        
        return Result(success=True, message="Minecraft server files and Dockerfile created successfully")
    
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
            - .:/server
        ports:
            - "{25565 + process.port_id}:{25565 + process.port_id}"
        restart: unless-stopped
        stdin_open: true
        tty: true
        mem_limit: 3g
""")
        return Result(success=True, message="Docker Compose file created successfully")
    except Exception as e:
        return Result(success=False, message=str(e))
