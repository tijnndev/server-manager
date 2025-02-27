from db import db
from models.base_model import BaseModel
from werkzeug.security import generate_password_hash, check_password_hash
from typing import Optional

class User(BaseModel):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(100), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True)
    role = db.Column(db.String(50), nullable=False, default="user")
    reset_token = db.Column(db.String(50), nullable=True)

    def __repr__(self):
        return f"<User {self.username}>"

    def as_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
    
    @classmethod
    def verify_reset_token(cls, token: str) -> Optional["User"]:
        """Finds a user by reset token."""
        return cls.query.filter_by(reset_token=token).first()

    def set_password(self, password: str):
        """Hashes and sets the password for the user."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Checks the provided password against the stored hash."""
        return check_password_hash(self.password_hash, password)
