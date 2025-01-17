import datetime
import os
import threading
import time

import requests
from flask import Flask, render_template, redirect, request, session, url_for, jsonify, g
from models.user import User
from routes.file_manager import file_manager_routes
from routes.service import service_routes
from flask_migrate import Migrate
from routes.process import process_routes
from models.discord_integration import DiscordIntegration
from werkzeug.security import generate_password_hash
from db import db
from dotenv import load_dotenv
import docker, logging
import subprocess
from routes.service import find_process_by_name

load_dotenv()

client = docker.from_env()

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.getenv('SECRET_KEY')

db.init_app(app)
migrate = Migrate(app, db)

def create_admin_user():
    if User.query.count() == 0:
        admin = User(username='admin', email="test@gmail.com", password_hash=generate_password_hash('JGR6jek5R6ivZTF^6b'))
        db.session.add(admin)
        db.session.commit()
        print("Admin user created successfully!")

def handle_event(event):
        if 'Actor' in event and 'Attributes' in event['Actor']:
            container_name_in_event = event['Actor']['Attributes'].get('name', '').split("_")[0]
            with app.app_context():
                process = find_process_by_name(container_name_in_event)
                if process == None or event["Type"] != "container":
                    return

                integration = DiscordIntegration.query.filter_by(service_id=process.id).first()

                if integration:
                    print(event['Action'])
                    # logging.critical("Handling event: %s", event)
                    # logging.debug(f"Event for {container_name_in_event}: {event['Type']} - {event['Action']}")
                    if event['Action'] in integration.events_list:
                        send_webhook_message(integration.webhook_url, event)

def start_listening_for_events():
    while True:
        for event in client.events(decode=True):
            handle_event(event)
            break

def run_event_listener():
    print("initialised event listener")
    event_listener_thread = threading.Thread(target=start_listening_for_events, daemon=True)
    event_listener_thread.start()

def send_webhook_message(webhook_url, event):
    """Send a message to the provided Discord webhook URL."""
    data = {
        "content": f"Event triggered: {event['Action']} for container {event['Actor']['Attributes'].get('name', 'Unknown')}"
    }

    try:
        response = requests.post(webhook_url, json=data)
        if response.status_code == 204:
            print("Webhook message sent successfully!")
        else:
            print(f"Failed to send webhook: {response.status_code} - {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending webhook message: {e}")

with app.app_context():
    run_event_listener()
    db.create_all()
    create_admin_user()

BASE_DIR = os.path.dirname(__file__)
ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, 'active-servers')
SERVICES_DIRECTORY = 'active-servers'

app.register_blueprint(process_routes, url_prefix='/process')
app.register_blueprint(service_routes, url_prefix='/services')
app.register_blueprint(file_manager_routes, url_prefix='/files')



## WEB
@app.route('/')
def dashboard():
    user = session.get('user', {'username': 'Guest'})
    return render_template('dashboard.html', user=user)

@app.before_request
def before_request():
    g.page = request.endpoint
    if ('username' not in session or 'user_id' not in session) and request.endpoint not in ['login', 'static', 'webhook']:
        return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Invalid username or password")

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/webhook', methods=['POST'])
def webhook():
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    signature = request.headers.get('X-Hub-Signature-256')
    
    if secret and signature:
        from hashlib import sha256
        import hmac
        payload = request.get_data()
        computed_signature = "sha256=" + hmac.new(secret.encode(), payload, sha256).hexdigest()
        if not hmac.compare_digest(computed_signature, signature):
            return jsonify({"error": "Invalid signature"}), 403

    event = request.headers.get('X-GitHub-Event')
    payload = request.json

    if event == "push":
        script_path = os.path.join(BASE_DIR, 'updater.sh')

        try:
            os.chmod(script_path, 0o755)  
        except subprocess.CalledProcessError as e:
            return jsonify({"error": f"Failed to set script permissions: {e}"}), 500
        
        try:
            subprocess.call([script_path])
            return jsonify({"message": "Script executed successfully!"}), 200
        except subprocess.CalledProcessError as e:
            return jsonify({"error": f"Script execution failed: {e}"}), 500

    return jsonify({"message": "Unhandled event"}), 200


logging.basicConfig(level=logging.CRITICAL)



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7001, debug=True)

