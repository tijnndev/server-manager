import json
from db import db
from models.base_model import BaseModel


class DiscordIntegration(BaseModel):
    __tablename__ = 'discord_integrations'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    process_name = db.Column(db.String(255), nullable=False, unique=True)
    webhook_url = db.Column(db.String(255), nullable=False)
    events = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<DiscordIntegration {self.process_name}>"

    @property
    def events_list(self):
        """Deserialize events from JSON to a Python list."""
        return json.loads(self.events) if self.events else []

    @events_list.setter
    def events_list(self, events):
        """Serialize events from a Python list to JSON."""
        self.events = json.dumps(events)
