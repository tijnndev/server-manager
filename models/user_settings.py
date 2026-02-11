from db import db
from models.base_model import BaseModel


class UserSettings(BaseModel):
    __tablename__ = 'user_settings'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    
    # Filter preferences
    remember_filters = db.Column(db.Boolean, nullable=False, default=False)
    filter_settings = db.Column(db.JSON, nullable=True)
    
    # Appearance preferences
    theme = db.Column(db.String(20), nullable=False, default='dark')  # 'dark' or 'light'
    compact_mode = db.Column(db.Boolean, nullable=False, default=False)
    console_font_size = db.Column(db.Integer, nullable=False, default=14)  # 10-20px
    
    # Behavior preferences
    auto_refresh_enabled = db.Column(db.Boolean, nullable=False, default=True)
    auto_refresh_interval = db.Column(db.Integer, nullable=False, default=5)  # seconds
    items_per_page = db.Column(db.Integer, nullable=False, default=25)  # for pagination
    notification_sounds = db.Column(db.Boolean, nullable=False, default=True)
    
    # Console preferences
    show_timestamps = db.Column(db.Boolean, nullable=False, default=True)
    console_word_wrap = db.Column(db.Boolean, nullable=False, default=True)
    
    # Discord integration
    discord_webhook_url = db.Column(db.String(500), nullable=True)
    discord_enabled = db.Column(db.Boolean, nullable=False, default=False)
    discord_notify_crashes = db.Column(db.Boolean, nullable=False, default=True)
    discord_notify_power_actions = db.Column(db.Boolean, nullable=False, default=True)

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
            "theme": self.theme,
            "compact_mode": self.compact_mode,
            "console_font_size": self.console_font_size,
            "auto_refresh_enabled": self.auto_refresh_enabled,
            "auto_refresh_interval": self.auto_refresh_interval,
            "items_per_page": self.items_per_page,
            "notification_sounds": self.notification_sounds,
            "show_timestamps": self.show_timestamps,
            "console_word_wrap": self.console_word_wrap,
            "discord_webhook_url": self.discord_webhook_url,
            "discord_enabled": self.discord_enabled,
            "discord_notify_crashes": self.discord_notify_crashes,
            "discord_notify_power_actions": self.discord_notify_power_actions,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    @classmethod
    def get_or_create(cls, user_id: int) -> "UserSettings":
        """Gets or creates user settings for a given user."""
        settings = cls.query.filter_by(user_id=user_id).first()
        if not settings:
            settings = cls(user_id=user_id)
            db.session.add(settings)
            db.session.commit()
        return settings

    def update_settings(self, **kwargs):
        """Updates user settings with provided keyword arguments."""
        for key, value in kwargs.items():
            if hasattr(self, key) and value is not None:
                setattr(self, key, value)
        db.session.commit()
