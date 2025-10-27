from db import db
from models.base_model import BaseModel
from typing import Optional


class UserSettings(BaseModel):
    __tablename__ = 'user_settings'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    remember_filters = db.Column(db.Boolean, nullable=False, default=False)
    filter_settings = db.Column(db.JSON, nullable=True)

    # Relationship to User
    user = db.relationship('User', backref=db.backref('settings', uselist=False, cascade='all, delete-orphan'))

    def __repr__(self):
        return f"<UserSettings user_id={self.user_id}>"

    def as_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "remember_filters": self.remember_filters,
            "filter_settings": self.filter_settings,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    @classmethod
    def get_or_create(cls, user_id: int) -> "UserSettings":
        """Gets or creates user settings for a given user."""
        settings = cls.query.filter_by(user_id=user_id).first()
        if not settings:
            settings = cls(user_id=user_id, remember_filters=False)
            db.session.add(settings)
            db.session.commit()
        return settings

    def update_settings(self, remember_filters: Optional[bool] = None, filter_settings: Optional[dict] = None):
        """Updates user settings."""
        if remember_filters is not None:
            self.remember_filters = remember_filters
        if filter_settings is not None:
            self.filter_settings = filter_settings
        db.session.commit()
