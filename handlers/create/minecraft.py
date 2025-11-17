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
        
        # Get Minecraft version from dependencies or use default
        mc_version = "latest"
        if process.dependencies:
            dependencies = process.dependencies.split(",") if isinstance(process.dependencies, str) else process.dependencies
            if dependencies and len(dependencies) > 0:
                mc_version = dependencies[0].strip()
        
        dockerfile_content = """FROM openjdk:21-jdk-slim
WORKDIR /server
COPY . /server

# Download Minecraft server jar if not present
RUN if [ ! -f server.jar ]; then \\
    apt-get update && apt-get install -y wget && \\
    wget -O server.jar https://launcher.mojang.com/v1/objects/$(wget -qO- https://launchermeta.mojang.com/mc/game/version_manifest.json | grep -oP '"latest":.*?"release":"\\K[^"]+' | head -1 | xargs -I {{}} wget -qO- https://launchermeta.mojang.com/mc/game/version_manifest.json | grep -oP '"id":"{{}}.*?"url":"\\K[^"]+' | xargs wget -qO- | grep -oP '"server":.*?"url":"https://launcher.mojang.com/v1/objects/\\K[^/]+' | head -1)/server.jar && \\
    apt-get clean; \\
fi

# Accept EULA
RUN echo "eula=true" > eula.txt

CMD ["sh", "-c", "java -Xmx2G -Xms1G -jar server.jar nogui"]
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
        # Always keep container running - process will be controlled via docker exec
        command: ["tail", "-f", "/dev/null"]
        ports:
            - "{25565 + process.port_id}:{25565 + process.port_id}"
        environment:
            - MAIN_COMMAND={json.dumps(process.command or "java -Xmx2G -Xms1G -jar server.jar nogui")}
        restart: unless-stopped
        stdin_open: true
        tty: true
        mem_limit: 3g
""")
        return Result(success=True, message="Docker Compose file created successfully")
    except Exception as e:
        return Result(success=False, message=str(e))
