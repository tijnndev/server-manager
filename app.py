import functools
import json
import redis, os, time, threading, requests, logging, subprocess, signal, sys
from flask import Flask, render_template, redirect, request, session, url_for, jsonify, g, flash
from models.user import User
from routes.file_manager import file_manager_routes
from routes.auth import auth_route
from routes.service import service_routes
from flask_migrate import Migrate
from routes.process import process_routes
from models.discord_integration import DiscordIntegration
from werkzeug.security import generate_password_hash
from db import db
from dotenv import load_dotenv
from utils import find_process_by_name, send_email, generate_reset_email_body, generate_random_string
from routes.nginx import nginx_routes
from decorators import auth_check, owner_or_subuser_required, has_permission
from routes.git import git_routes

load_dotenv()

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
app.secret_key = os.getenv('SECRET_KEY')

db.init_app(app)
migrate = Migrate(app, db)

def create_admin_user():
    if User.query.count() == 0:
        admin = User(username='admin', role="admin", email="test@gmail.com", password_hash=generate_password_hash('tDIg2uDuSOf0b!Uc82'))
        db.session.add(admin)
        db.session.commit()
        print("Admin user created successfully!")

processed_events = {}
processed_events_lock = threading.Lock()
EVENT_EXPIRATION_TIME = 30

def handle_event(event):
    if 'Actor' in event and 'Attributes' in event['Actor']:
        container_name_in_event = event['Actor']['Attributes'].get('name', '').split("_")[0]
        container_id = event['Actor']['ID']

        current_time = time.time()
        event_key = f"{container_id}_{event['Action']}"

        with processed_events_lock:
            if event_key in processed_events:
                last_event_time = processed_events[event_key]
                if current_time - last_event_time < EVENT_EXPIRATION_TIME:
                    print(f"Skipping duplicate event: {event_key}")
                    return

            processed_events[event_key] = current_time

        print(f"Event processed: {event_key}")

        with app.app_context():
            process = find_process_by_name(container_name_in_event)
            if process is None or event["Type"] != "container":
                return

            integration = DiscordIntegration.query.filter_by(service_id=process.id).first()
            if integration and event['Action'] in integration.events_list:
                # print(f"Sending webhook for event: {event['Action']}")
                send_webhook_message(integration.webhook_url, event)



def start_listening_for_events():
    while True:
        result = subprocess.run(["docker", "events", "--format", "{{json .}}"], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
                handle_event(event)
            except json.JSONDecodeError:
                continue
        time.sleep(1)

                    
def run_event_listener():
    print('Listening event')
    event_listener_thread = threading.Thread(target=start_listening_for_events, daemon=True)
    event_listener_thread.start()

def send_webhook_message(webhook_url, event):
    data = {
        "content": f"Event triggered: {event['Action']} for container {event['Actor']['Attributes'].get('name', 'Unknown')}"
    }

    try:
        response = requests.post(webhook_url, json=data)
        if response.status_code == 204:
            # print(event)
            print("Webhook message sent successfully!")
        else:
            print(f"Failed to send webhook: {response.status_code} - {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending webhook message: {e}")

redis_client = redis.StrictRedis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    decode_responses=True
)

REDIS_LOCK_KEY = "first_worker_lock"
LOCK_TTL = 3600

def is_first_worker():
    current_pid = os.getpid()

    is_first = redis_client.set(REDIS_LOCK_KEY, current_pid, nx=True, ex=LOCK_TTL)
    if is_first:
        print(f"First worker detected with PID: {current_pid}")
        return True

    lock_owner = redis_client.get(REDIS_LOCK_KEY)
    print(f"Current worker PID: {current_pid}, First worker PID: {lock_owner}")
    return str(current_pid) == lock_owner

with app.app_context():
    if is_first_worker():
        run_event_listener()
    db.create_all()
    create_admin_user()

BASE_DIR = os.path.dirname(__file__)
ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, 'active-servers')
SERVICES_DIRECTORY = 'active-servers'

app.register_blueprint(process_routes, url_prefix='/process')
app.register_blueprint(service_routes, url_prefix='/services')
app.register_blueprint(file_manager_routes, url_prefix='/files')
app.register_blueprint(nginx_routes, url_prefix='/nginx')
app.register_blueprint(git_routes, url_prefix='/git')
app.register_blueprint(auth_route, url_prefix='/auth')


## WEB
@app.route('/')
@auth_check()
def dashboard():
    user = session.get('username')
    return render_template('dashboard.html', user=user)

@app.before_request
def before_request():
    g.page = request.endpoint


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


# logging.basicConfig(level=logging.INFO)

def cleanup_redis_key(*args):
    redis_client.delete(REDIS_LOCK_KEY)
    print(f"Redis lock key {REDIS_LOCK_KEY} removed for PID: {os.getpid()}")
    sys.exit(0)

signal.signal(signal.SIGTERM, cleanup_redis_key)
signal.signal(signal.SIGINT, cleanup_redis_key)

@app.context_processor # type: ignore
def inject_static_vars():
    return {
        'has_permission': has_permission
    }

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7001, debug=True)

