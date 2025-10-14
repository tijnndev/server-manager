import os
import subprocess
from db import db
from models.base_model import BaseModel
from models.discord_integration import DiscordIntegration
from extra import get_project_root

BASE_DIR = get_project_root()
ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, 'active-servers')

class Process(BaseModel):
    __tablename__ = 'processes'

    id = db.Column(db.String(255), primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    command = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    file_location = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    domain = db.Column(db.String(255), nullable=True)
    dependencies = db.Column(db.JSON, nullable=True)
    port_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    process_pid = db.Column(db.Integer, nullable=True)

    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    def __repr__(self):
        return f"<Process {self.name}>"
    

    @property
    def status(self):
        name = self.name
        process = self
        if not process:
            return {"error": "Process not found"}
        def is_always_running_container(name):
            try:
                process_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
                os.chdir(process_dir)

                # Get container ID
                result = subprocess.run(['docker-compose', 'ps', '-q', name], capture_output=True, text=True, check=True)
                container_id = result.stdout.strip()

                if not container_id:
                    return False

                # Check for MAIN_COMMAND in environment
                result = subprocess.run(['docker', 'inspect', '--format', '{{range .Config.Env}}{{println .}}{{end}}', container_id],
                                    capture_output=True, text=True)
                
                for line in result.stdout.split('\n'):
                    if line.startswith('MAIN_COMMAND='):
                        return True
                
                return False

            except Exception:
                return False
        def check_process_running_in_container(name):
            """Check if the main process is running inside the container"""
            try:
                process_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
                os.chdir(process_dir)

                # Get container ID
                result = subprocess.run(['docker-compose', 'ps', '-q', name], capture_output=True, text=True, check=True)
                container_id = result.stdout.strip()

                if not container_id:
                    return {"status": "Container Not Running", "container_running": False}

                # Check if container is running
                result = subprocess.run(['docker', 'inspect', '--format', '{{.State.Status}}', container_id], 
                                    capture_output=True, text=True)
                
                container_status = result.stdout.strip()
                
                if result.returncode != 0 or container_status != 'running':
                    return {"status": "Container Not Running", "container_running": False}

                # Get the main command from environment variable
                result = subprocess.run(['docker', 'inspect', '--format', '{{range .Config.Env}}{{println .}}{{end}}', container_id],
                                    capture_output=True, text=True)
                
                
                main_command = None
                for line in result.stdout.split('\n'):
                    if line.startswith('MAIN_COMMAND='):
                        main_command = line.split('=', 1)[1].strip('"')
                        break

                if not main_command:
                    return {"status": "Running", "container_running": True, "process_running": True}

                # Check if the main process is running inside the container
                result = subprocess.run(['docker', 'exec', container_id, 'ps', 'aux'], 
                                    capture_output=True, text=True)
                
                if result.returncode != 0:
                    return {"status": "Process Stopped", "container_running": True, "process_running": False}

                # Parse process list to find our main command
                processes = result.stdout
                command_parts = main_command.split()
                
                # Look for the main command in the process list (exclude zombie processes)
                process_running = False
                matching_processes = []
                for line in processes.split('\n')[1:]:  # Skip header
                    if line.strip():
                        # Check if this is a zombie process (contains <defunct> or Z state)
                        if '<defunct>' in line or ' Z ' in line:
                            continue
                            
                        # Check if any part of our command appears in the process line
                        if any(part in line for part in command_parts if len(part) > 2):
                            process_running = True
                            matching_processes.append(line.strip())

                if process_running:
                    return {"status": "Running", "container_running": True, "process_running": True}
                else:
                    return {"status": "Process Stopped", "container_running": True, "process_running": False}

            except subprocess.CalledProcessError as e:
                return {"status": "Error", "error": f"Failed to check process status: {e.stderr}"}
            except Exception as e:
                return {"status": "Error", "error": str(e)}

        # Check if this is an always-running container
        if is_always_running_container(name):
            # Use the new process-aware status checking
            return check_process_running_in_container(name)
        else:
            # Use traditional container status checking for legacy containers
            try:
                process_dir = os.path.join(ACTIVE_SERVERS_DIR, name)
                os.chdir(process_dir)

                result = subprocess.run(['docker-compose', 'ps', '-q', name], capture_output=True, text=True, check=True)
                container_id = result.stdout.strip()

                if not container_id:
                    return {"process": name, "status": "Exited"}

                result = subprocess.run(['docker', 'inspect', '--format', '{{.State.Status}}', container_id], capture_output=True, text=True)

                if result.returncode != 0:
                    return {"error": "Failed to get process status from docker inspect."}

                container_status = result.stdout.strip()

                if container_status == 'running':
                    return {"process": name, "status": "Running"}
                
                return {"process": name, "status": "Exited"}

            except subprocess.CalledProcessError as e:
                return {"error": f"Failed to get process status: {e.stderr}"}
            except Exception as e:
                return {"error": str(e)}

    def as_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "command": self.command,
            "type": self.type,
            "file_location": self.file_location,
            "description": self.description,
            "dependencies": self.dependencies,
            "process_pid": self.process_pid,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    def update_id(self, new_name: str):
        try:
            integration = DiscordIntegration.query.filter_by(process_name=self.name).first()
            if integration:
                integration.process_name = new_name
                db.session.add(integration)
                print(f"Updated DiscordIntegration for process_name: {new_name}")
            else:
                print('No discord integration found')

            self.id = new_name
            db.session.add(self)

            db.session.commit()
            print(f"Updated process ID to: {new_name}")
        
        except Exception as e:
            db.session.rollback()
            print(f"Failed to update ID for {self.name}: {e}")
            raise
