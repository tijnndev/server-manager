from db import db
from models.base_model import BaseModel
import docker
from models.discord_integration import DiscordIntegration

client = docker.from_env()

class Process(BaseModel):
    __tablename__ = 'processes'

    id = db.Column(db.String(255), primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    command = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    file_location = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    dependencies = db.Column(db.JSON, nullable=True)
    port_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    def __repr__(self):
        return f"<Process {self.name}>"

    def as_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "command": self.command,
            "type": self.type,
            "file_location": self.file_location,
            "description": self.description,
            "dependencies": self.dependencies,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    def update_id(self, new_id: str):
        try:
            integration = DiscordIntegration.query.filter_by(service_id=self.id).first()
            if integration:
                integration.service_id = new_id 
                db.session.add(integration)
                print(f"Updated DiscordIntegration for service_id: {new_id}")
            else:
                print('No discord integration found')

            self.id = new_id
            db.session.add(self)

            db.session.commit()
            print(f"Updated process ID to: {new_id}")
        
        except Exception as e:
            db.session.rollback()
            print(f"Failed to update ID for {self.name}: {e}")
            raise
