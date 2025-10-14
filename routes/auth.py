from flask import Blueprint, request, render_template, url_for, redirect, session, flash
from models.user import User
from werkzeug.security import generate_password_hash
from utils import generate_random_string, send_email, generate_reset_email_body
from db import db

auth_route = Blueprint('auth', __name__)


@auth_route.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            session["role"] = user.role
            return redirect(url_for('dashboard'))
        
        flash("Invalid username or password")

    return render_template('auth/login.html', page_title="Login")


@auth_route.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if password != confirm_password:
            flash("Passwords do not match")
            return redirect(url_for('register'))

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash("Username already exists")
            return redirect(url_for('auth.register'))
        
        existing_email = User.query.filter_by(email=email).first()
        if existing_email:
            flash("Email already registered")
            return redirect(url_for('auth.register'))

        new_user = User(username=username, email=email, password_hash=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()

        flash("Registration successful! Please log in.")
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html', page_title="Register")


@auth_route.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        
        if user:
            token = generate_random_string(10)
            user.reset_token = token
            db.session.add(user)
            db.session.commit()
            reset_url = url_for('auth.reset_token', token=token, _external=True)

            email_body = generate_reset_email_body(reset_url)
            send_email(
                user.email,
                'Reset Your Password',
                email_body
            )
            flash('An email with instructions has been sent!', 'info')
        else:
            flash('Email not found.', 'danger')

        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', page_title="Reset Password")


@auth_route.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_token(token):
    user = User.verify_reset_token(token=token)
    if not user:
        flash('That is an invalid or expired token', 'warning')
        return redirect(url_for('auth.reset_password'))

    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if password != confirm_password:
            flash("Passwords do not match", 'danger')
            return redirect(url_for('auth.reset_token', token=token))

        user.password_hash = generate_password_hash(password)
        user.reset_token = None
        db.session.add(user)
        db.session.commit()
        flash('Your password has been updated!', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_token.html', token=token, page_title="Reset Password")


@auth_route.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
