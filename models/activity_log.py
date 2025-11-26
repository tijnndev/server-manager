from db import db
from datetime import datetime


class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    username = db.Column(db.String(100), nullable=False)
    action = db.Column(db.String(100), nullable=False)  # e.g., "started_process", "deleted_file", "updated_settings"
    target = db.Column(db.String(255))  # e.g., process name, file name
    details = db.Column(db.Text)  # Additional JSON details
    ip_address = db.Column(db.String(45))  # Support IPv6
    user_agent = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationship
    user = db.Relationship('User', backref='activity_logs')
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.username,
            'action': self.action,
            'target': self.target,
            'details': self.details,
            'ip_address': self.ip_address,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }
    
    @staticmethod
    def log_activity(user_id, username, action, target=None, details=None, request_obj=None):
        """Helper method to log an activity"""
        ip_address = None
        user_agent = None
        
        if request_obj:
            ip_address = request_obj.remote_addr
            user_agent = request_obj.headers.get('User-Agent', '')[:255]
        
        activity = ActivityLog(
            user_id=user_id,
            username=username,
            action=action,
            target=target,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        db.session.add(activity)
        db.session.commit()
        return activity
