from gevent import monkey

# Patch standard library early for gevent compatibility (must happen before any other imports)
monkey.patch_all()

import redis, os, time, threading, subprocess, signal, sys, cpuinfo, json, socket, psutil, hmac, secrets, logging
from flask import Flask, render_template, request, session, jsonify, g
from flask_caching import Cache
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from models.user import User
from models.user_settings import UserSettings
from routes.file_manager import file_manager_routes
from routes.auth import auth_route
from routes.process import process_routes
from routes.email import email_routes
from routes.settings import settings_routes
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash
from db import db
from dotenv import load_dotenv
from utils import find_process_by_name
from routes.nginx import nginx_routes
from decorators import auth_check, has_permission
from routes.git import git_routes
from hashlib import sha256

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('server-manager')


app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Database connection pool optimization for high concurrency
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 20,              # Connection pool size (increased for 32 workers)
    'max_overflow': 40,            # Additional connections when pool is exhausted
    'pool_timeout': 30,            # Seconds to wait for connection from pool
    'pool_recycle': 3600,          # Recycle connections after 1 hour
    'pool_pre_ping': True,         # Verify connections before using them
    'echo_pool': False,            # Disable pool logging in production
}

app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
app.secret_key = os.getenv('SECRET_KEY')

# Redis-backed caching configuration
app.config['CACHE_TYPE'] = 'redis'
app.config['CACHE_REDIS_HOST'] = os.getenv('REDIS_HOST', 'localhost')
app.config['CACHE_REDIS_PORT'] = int(os.getenv('REDIS_PORT', 6379))
app.config['CACHE_REDIS_DB'] = 1  # Use separate DB from worker coordination
app.config['CACHE_DEFAULT_TIMEOUT'] = 300  # 5 minutes default cache
app.config['CACHE_KEY_PREFIX'] = 'sm_'

# Initialize cache
cache = Cache(app)

# Initialize CSRF protection
csrf = CSRFProtect(app)

# Initialize rate limiter (uses Redis for shared state across workers)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri=f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}/2",
    default_limits=["200 per minute"],
)

# Cache CPU name at startup since it never changes
CPU_NAME = cpuinfo.get_cpu_info()["brand_raw"]

ENVIRONMENT = os.getenv("ENVIRONMENT")

db.init_app(app)
migrate = Migrate(app, db)


# Custom Jinja2 filters
@app.template_filter('timestamp_to_date')
def timestamp_to_date_filter(timestamp):
    """Convert Unix timestamp to human-readable date"""
    from datetime import datetime
    try:
        dt = datetime.fromtimestamp(timestamp)
        now = datetime.now()
        diff = now - dt
        
        if diff.days == 0:
            if diff.seconds < 60:
                return "Just now"
            elif diff.seconds < 3600:
                minutes = diff.seconds // 60
                return f"{minutes} min{'s' if minutes > 1 else ''} ago"
            else:
                hours = diff.seconds // 3600
                return f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif diff.days == 1:
            return "Yesterday"
        elif diff.days < 7:
            return f"{diff.days} days ago"
        else:
            return dt.strftime("%b %d, %Y")
    except:
        return "Unknown"


def create_admin_user():
    if User.query.count() == 0:
        admin_password = os.getenv('ADMIN_PASSWORD')
        if not admin_password:
            admin_password = secrets.token_urlsafe(16)
            logger.warning(f"No ADMIN_PASSWORD env var set. Generated random password: {admin_password}")
            logger.warning("Set ADMIN_PASSWORD in .env to use a fixed password.")
        admin_email = os.getenv('ADMIN_EMAIL', 'admin@localhost')
        admin = User(username='admin', role="admin", email=admin_email, password_hash=generate_password_hash(admin_password))
        db.session.add(admin)
        db.session.commit()
        logger.info("Admin user created successfully!")


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

            # Discord integration removed


def start_listening_for_events():
    while True:
        try:
            process = subprocess.Popen(
                ["docker", "events", "--format", "{{json .}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            for line in iter(process.stdout.readline, ''):
                try:
                    event = json.loads(line.strip())
                    handle_event(event)
                except json.JSONDecodeError:
                    continue
            process.wait()
        except Exception as e:
            logger.error(f"Event listener error: {e}")
        time.sleep(5)  # Retry after failure

                    
def run_event_listener():
    print('Listening event')
    event_listener_thread = threading.Thread(target=start_listening_for_events, daemon=True)
    event_listener_thread.start()


first_worker = None
if ENVIRONMENT == "production":
    redis_client = redis.StrictRedis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', "6379")),
        decode_responses=True
    )

    REDIS_LOCK_KEY = "first_worker_lock"
    LOCK_TTL = 3600

    current_pid = os.getpid()

    is_first = redis_client.set(REDIS_LOCK_KEY, current_pid, nx=True, ex=LOCK_TTL)
    if is_first:
        print(f"First worker detected with PID: {current_pid}")
        first_worker = True

    lock_owner = redis_client.get(REDIS_LOCK_KEY)
    print(f"Current worker PID: {current_pid}, First worker PID: {lock_owner}")
    first_worker = (str(current_pid) == lock_owner)

    def cleanup_redis_key(*_args):
        redis_client.delete(REDIS_LOCK_KEY)
        print(f"Redis lock key {REDIS_LOCK_KEY} removed for PID: {os.getpid()}")
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup_redis_key)
    signal.signal(signal.SIGINT, cleanup_redis_key)


with app.app_context():
    if ENVIRONMENT == "production" and first_worker:
        run_event_listener()
    db.create_all()
    create_admin_user()

BASE_DIR = os.path.dirname(__file__)
ACTIVE_SERVERS_DIR = os.path.join(BASE_DIR, 'active-servers')
PROCESS_DIRECTORY = 'active-servers'

from routes.activity import activity_routes

app.register_blueprint(process_routes, url_prefix='/process')
app.register_blueprint(file_manager_routes, url_prefix='/files')
app.register_blueprint(nginx_routes, url_prefix='/nginx')
app.register_blueprint(git_routes, url_prefix='/git')
app.register_blueprint(auth_route, url_prefix='/auth')

# Apply rate limiting to auth blueprint (brute-force protection)
limiter.limit("5/minute")(auth_route)
app.register_blueprint(email_routes, url_prefix='/email')
app.register_blueprint(settings_routes, url_prefix='/settings')
app.register_blueprint(activity_routes, url_prefix='/activity')


# WEB
@app.route('/')
@auth_check()
def dashboard():
    user = session.get('username')
    return render_template('dashboard.html', page_title="Dashboard", user=user)


@app.route('/api/server/stats')
@auth_check()
@cache.cached(timeout=5, key_prefix='server_stats')  # Cache for 5 seconds
def get_server_stats():
    stats = {
        "cpu_name": CPU_NAME,
        "cpu_usage": psutil.cpu_percent(interval=1),
        "memory_allocated": psutil.virtual_memory().total // (1024 * 1024),
        "memory_usage": psutil.virtual_memory().percent,
        "storage_allocated": psutil.disk_usage('/').total // (1024 * 1024 * 1024),
        "storage_usage": psutil.disk_usage('/').percent,
        "network_usage": psutil.net_io_counters().bytes_sent // (1024 * 1024) + psutil.net_io_counters().bytes_recv // (1024 * 1024)
    }
    return jsonify(stats)


@app.before_request
def before_request():
    g.page = request.endpoint


@app.route('/webhook', methods=['POST'])
def webhook():
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    signature = request.headers.get('X-Hub-Signature-256')
    
    if secret and signature:
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


@app.context_processor
def inject_static_vars():
    server_ip = socket.gethostbyname(socket.gethostname())
    return {
        'has_permission': has_permission,
        'server_ip': server_ip
    }


# Initialize process monitoring
def init_process_monitoring():
    """Initialize background process monitoring for crash detection."""
    try:
        from utils.process_monitor import start_process_monitoring
        # Start monitoring with 30 second interval
        start_process_monitoring(interval=30)
        logger.info("Process monitoring initialized")
    except Exception as e:
        logger.error(f"Failed to start process monitoring: {e}")


# Start monitoring when app starts (only in production)
if ENVIRONMENT == "production":
    init_process_monitoring()


@app.route('/health')
@csrf.exempt
def health_check():
    """Health check endpoint for monitoring and load balancers."""
    health = {"status": "ok", "checks": {}}

    # Check database
    try:
        with app.app_context():
            db.session.execute(db.text('SELECT 1'))
        health["checks"]["database"] = "ok"
    except Exception as e:
        health["checks"]["database"] = f"error: {str(e)}"
        health["status"] = "degraded"

    # Check Redis
    try:
        test_redis = redis.StrictRedis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            decode_responses=True
        )
        test_redis.ping()
        health["checks"]["redis"] = "ok"
    except Exception as e:
        health["checks"]["redis"] = f"error: {str(e)}"
        health["status"] = "degraded"

    # Check Docker daemon
    try:
        result = subprocess.run(['docker', 'info'], capture_output=True, text=True, timeout=5)
        health["checks"]["docker"] = "ok" if result.returncode == 0 else "error"
    except Exception as e:
        health["checks"]["docker"] = f"error: {str(e)}"
        health["status"] = "degraded"

    status_code = 200 if health["status"] == "ok" else 503
    return jsonify(health), status_code


if __name__ == "__main__":
    # Also start monitoring in development mode
    if ENVIRONMENT != "production":
        init_process_monitoring()
    app.run(host="0.0.0.0", port=7001, debug=True)
