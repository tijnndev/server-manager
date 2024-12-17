from db import db
from models.base_model import BaseModel
import docker

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
    def get_status(self):
        container = client.containers.get(self.id)
        status = container.status
        return status