import os
from db import db
from models.base_model import BaseModel

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, 'active-servers')

class Process(BaseModel):
    __tablename__ = 'processes'

    id = db.Column(db.String(255), primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    command = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    file_location = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    domain = db.Column(db.String(255), nullable=True)
    dependencies = db.Column(db.JSON, nullable=True)
    port_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    process_pid = db.Column(db.Integer, nullable=True)

    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

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
            "process_pid": self.process_pid,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    def update_id(self, new_name: str):
        try:
            self.id = new_name
            db.session.add(self)

            db.session.commit()
            print(f"Updated process ID to: {new_name}")
        
        except Exception as e:
            db.session.rollback()
            print(f"Failed to update ID for {self.name}: {e}")
            raise
