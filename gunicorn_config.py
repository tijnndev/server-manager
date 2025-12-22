"""
Gunicorn configuration optimized for AMD Ryzen 9 7950X3D (16 cores/32 threads)
This configuration maximizes performance for your powerful hardware.
"""
import os

# Server socket
bind = "0.0.0.0:7001"
backlog = 2048

# Worker processes
# For CPU-bound: (2 * CPU cores) + 1
# For I/O-bound (like your app): (4 * CPU cores)
# With 16 cores, we'll use 32 workers for optimal throughput
workers = int(os.getenv("GUNICORN_WORKERS", "32"))

# Worker class - gevent for async I/O operations
# Perfect for handling Docker operations, subprocess calls, and database queries
worker_class = "gevent"

# Worker connections - each gevent worker can handle 1000+ concurrent connections
worker_connections = 1000

# Threads per worker (not used with gevent, but keeping for reference)
threads = 1

# Timeout settings
# Increased for long-running Docker operations
timeout = 120
graceful_timeout = 30
keepalive = 5

# Process naming
proc_name = "server-manager"

# Logging
accesslog = "/var/log/server-manager/access.log"
errorlog = "/var/log/server-manager/error.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Server mechanics
daemon = False
pidfile = "/var/run/server-manager.pid"
user = None
group = None
tmp_upload_dir = None

# Performance tuning
preload_app = True  # Load application code before worker processes are forked
max_requests = 5000  # Restart workers after this many requests (prevents memory leaks)
max_requests_jitter = 500  # Add randomness to max_requests to prevent all workers restarting simultaneously

# Security
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190

# Worker lifecycle callbacks
def on_starting(server):
    """Called just before the master process is initialized."""
    print(f"Starting Gunicorn with {workers} workers using {worker_class} worker class")
    
def when_ready(server):
    """Called just after the server is started."""
    print("Server is ready. Spawning workers")

def on_reload(server):
    """Called when the configuration is reloaded."""
    print("Reloading configuration")

def worker_int(worker):
    """Called when a worker receives the SIGINT or SIGQUIT signal."""
    print(f"Worker {worker.pid} received SIGINT/SIGQUIT")

def pre_fork(server, worker):
    """Called just before a worker is forked."""
    pass

def post_fork(server, worker):
    """Called just after a worker has been forked."""
    print(f"Worker spawned (pid: {worker.pid})")

def pre_exec(server):
    """Called just before a new master process is forked."""
    print("Forking new master process")

def worker_exit(server, worker):
    """Called just after a worker has been exited."""
    print(f"Worker {worker.pid} exited")
