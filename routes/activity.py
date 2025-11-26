from flask import Blueprint, render_template, jsonify, request, session
from models.activity_log import ActivityLog
from models.user import User
from decorators import owner_or_subuser_required
from sqlalchemy import desc
from db import db

activity_routes = Blueprint('activity', __name__, url_prefix='/activity')


@activity_routes.route('/', methods=['GET'])
@owner_or_subuser_required()
def activity_log():
    """Activity log page"""
    return render_template('activity/index.html', page_title="Activity Log")


@activity_routes.route('/api/logs', methods=['GET'])
@owner_or_subuser_required()
def get_activity_logs():
    """API endpoint to fetch activity logs"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    action_filter = request.args.get('action', None)
    user_filter = request.args.get('user', None)
    
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    
    # Build query
    query = ActivityLog.query
    
    # Apply filters
    if action_filter:
        query = query.filter(ActivityLog.action == action_filter)
    
    if user_filter:
        query = query.filter(ActivityLog.username.ilike(f'%{user_filter}%'))
    
    # Non-admin users can only see their own logs
    if user.role != 'admin':
        query = query.filter(ActivityLog.user_id == user_id)
    
    # Order by most recent first
    query = query.order_by(desc(ActivityLog.timestamp))
    
    # Paginate
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    logs = [log.to_dict() for log in pagination.items]
    
    return jsonify({
        'success': True,
        'logs': logs,
        'total': pagination.total,
        'page': page,
        'pages': pagination.pages,
        'per_page': per_page
    })


@activity_routes.route('/api/actions', methods=['GET'])
@owner_or_subuser_required()
def get_available_actions():
    """Get list of all available action types for filtering"""
    actions = db.session.query(ActivityLog.action).distinct().all()
    return jsonify({
        'success': True,
        'actions': [action[0] for action in actions]
    })
