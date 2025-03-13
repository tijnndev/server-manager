import functools
from flask import session, redirect, request
from models.process import Process
from models.subuser import SubUser
from models.user import User


def auth_check():
    def decorator(func):
        @functools.wraps(func)
        def decorated_auth_check(*args, **kwargs):
            if not session.get('user_id') or not session.get('username'):
                session.clear()
                return redirect(f'/auth/login?redirect={request.path}')
            return func(*args, **kwargs)
        return decorated_auth_check
    return decorator


def owner_or_subuser_required():
    def decorator(func):
        @functools.wraps(func)
        def decorated_auth_check(*args, **kwargs):
            if session.get("role") == "admin":
                return func(*args, **kwargs)

            user_id = session.get('user_id')
            user = User.query.get(user_id)
            if not user_id or not user:
                session.clear()
                return redirect(f'/auth/login?redirect={request.path}')
            
            process_name = kwargs.get('name')
            if not process_name:
                return redirect('/')

            is_owner = Process.query.filter_by(name=process_name, owner_id=user_id).first()
            if is_owner:
                return func(*args, **kwargs)

            subuser = SubUser.query.filter_by(email=user.email, process=process_name).first()
            if subuser:
                permissions = subuser.permissions or []
                for permission in permissions:
                    if permission in func.__name__:
                        return func(*args, **kwargs)

            return redirect('/')

        return decorated_auth_check
    return decorator


def owner_required():
    def decorator(func):
        @functools.wraps(func)
        def decorated_auth_check(*args, **kwargs):
            if session.get("role") == "admin":
                return func(*args, **kwargs)

            user_id = session.get('user_id')
            if not user_id:
                session.clear()
                return redirect(f'/auth/login?redirect={request.path}')

            user = User.query.get(user_id)
            if not user:
                session.clear()
                return redirect(f'/auth/login?redirect={request.path}')
            
            process_name = kwargs.get('name')
            if not process_name:
                return redirect('/')

            is_owner = Process.query.filter_by(name=process_name, owner_id=user_id).first()
            if not is_owner:
                return redirect('/')

            return func(*args, **kwargs)

        return decorated_auth_check
    return decorator


def has_permission(name: str, permission: str) -> bool:
    if session.get("role") == "admin":
        return True

    user_id = session.get('user_id')
    if not user_id:
        return False

    user = User.query.get(user_id)
    if not user:
        return False

    is_owner = Process.query.filter_by(name=name, owner_id=user_id).first()
    if is_owner:
        return True

    subuser = SubUser.query.filter_by(email=user.email).first()
    if not subuser or not subuser.permissions:
        return False

    return permission in subuser.permissions
