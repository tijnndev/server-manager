from db import db
from models.base_model import BaseModel

class SubUser(BaseModel):
    __tablename__ = 'sub_users'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email = db.Column(db.String(50), db.ForeignKey('users.email'), primary_key=True)
    permissions = db.Column(db.JSON, nullable=False, default=[])
    sub_role = db.Column(db.String(50), nullable=False, default="sub_user")
    process = db.Column(db.String(50), nullable=False)

    def __repr__(self):
        return f"<SubUser {self.sub_username}>"

    def as_dict(self):
        return {
            "email": self.email,
            "sub_role": self.sub_role,
            "permissions": self.permissions,
            "process": self.process,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }