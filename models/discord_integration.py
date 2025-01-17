from db import db
from models.base_model import BaseModel
from sqlalchemy.dialects.postgresql import ARRAY

class DiscordIntegration(BaseModel):
    __tablename__ = 'discord_integrations'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    service_name = db.Column(db.String(100), nullable=False, unique=True)
    webhook_url = db.Column(db.String(255), nullable=False)
    events = db.Column(ARRAY(db.String), nullable=True)

    def __repr__(self):
        return f"<DiscordIntegration {self.service_name}>"
