# Server Manager — Improvements

> Speed fixes, bug reports, and improvement suggestions. March 2026.
> 
> **Status: Most items IMPLEMENTED ✅** — see checkmarks below.

---

## 🚀 Speed Improvements

### ✅ IMPLEMENTED: Batch Docker Status Fetching

**Problem:** The dashboard made **N separate `docker-compose ps` calls** (one per container) to check status. Each call takes 1-3 seconds because `docker-compose` is a slow Python CLI that parses YAML, connects to the Docker daemon, etc. With 20 containers, the dashboard took 20-60 seconds to load.

**Fix applied in `routes/process.py`:**
- Added `_get_all_container_statuses()` — a single `docker ps -a --format ...` call that fetches ALL container names, IDs, and states in ~200ms regardless of container count.
- Replaced the `ThreadPoolExecutor` + per-container `get_process_status()` in `load_process()` with a simple loop over pre-fetched batch data.
- **Result: Dashboard load reduced from ~30s to ~1-2s for 20 containers.**

### ✅ IMPLEMENTED: Batch Metrics Endpoint

**Problem:** The dashboard JavaScript called `/process/metrics/<name>` **sequentially** for each running container, each spawning a separate `docker stats --no-stream` subprocess. With 10 running containers, this added 10-30 seconds of API calls every 5 seconds.

**Fix applied:**
- Added `_get_all_container_stats()` — a single `docker stats --no-stream --format ...` call that fetches CPU/memory for ALL containers at once.
- Added `/process/all-metrics` endpoint that returns all metrics in one response.
- Updated `dashboard.html` `fetchProcessMetrics()` to call the batch endpoint instead of N individual ones.
- **Result: Metrics fetching reduced from N×(1-3s) to 1×(2-3s).**

---

### ✅ IMPLEMENTED: Additional Speed Improvements

#### ✅ 1. Remove `Process.status` Property Subprocess Calls
**File:** `models/process.py`  
**Fix applied:** Removed entire `@property status` (200+ lines of subprocess calls). Model is now a pure data object. Status is only fetched via route-level batch methods.

#### ✅ 2. Cache `is_always_running_container()` Results
**File:** `utils.py`  
**Fix applied:** Added `_ALWAYS_RUNNING_CACHE` dict with 30-second TTL. Avoids repeated subprocess calls for the same container.

#### ✅ 3. Replace `os.chdir()` with `cwd=` Parameter
**Files:** `utils.py`, `routes/process.py`  
**Fix applied:** Replaced ALL `os.chdir()` calls with `cwd=` parameter on subprocess calls. Eliminates thread-safety issues.

#### ✅ 4. Reduce Gunicorn Workers
**File:** `gunicorn_config.py`  
**Fix applied:** Reduced default from 32 to 6 workers. Each gevent worker handles 1000+ connections, so 6 × 1000 = 6000 concurrent connections.

#### ✅ 5. Cache `cpuinfo.get_cpu_info()` Result
**File:** `app.py`  
**Fix applied:** CPU name is now cached at startup as `CPU_NAME` constant.

#### ✅ 6. Use `docker compose` (v2) Instead of `docker-compose` (v1)
**Files:** `utils.py`, `routes/process.py`  
**Fix applied:** All `['docker-compose', ...]` command calls replaced with `['docker', 'compose', ...]`. Docker Compose v2 is 2-5x faster.

#### 🔧 TODO: 7. WebSocket for Console Instead of SSE + Polling
**File:** `routes/process.py` lines 730-900  
**Problem:** The console log streaming uses SSE with internal polling. This creates subprocess overhead.  
**Fix:** Use `flask-socketio` with WebSocket transport. *Not yet implemented — significant refactor.*

---

## 🐛 Bugs

### ✅ Bug 1: `os.chdir()` Race Condition (Fixed)
**Fix applied:** All `os.chdir()` replaced with `cwd=` parameter across `utils.py` and `routes/process.py`.

### ✅ Bug 2: Uptime Calculation Off by 2 Hours (Fixed)
**File:** `routes/process.py` `calculate_uptime()`  
**Fix applied:** Removed hardcoded `- 2` hour offset. Now uses proper UTC timezone math — Docker's `StartedAt` timestamp is parsed as UTC and compared to `datetime.now(timezone.utc)`.

### 🔧 Bug 3: `get_process_status()` Return Type Inconsistency
**Description:** Return type varies between dict formats. *Not yet standardized — would require touching all callers.*

### ✅ Bug 4: In-Memory Cache Not Shared Across Workers (Fixed)
**File:** `routes/process.py`  
**Fix applied:** Replaced `PROCESS_STATUS_CACHE` in-memory dict with Redis-backed caching using `setex`/`get` with automatic TTL expiration. All workers now share the same cache.

### ✅ Bug 5: Duplicate Import (Fixed)
**File:** `app.py`  
**Fix applied:** Removed duplicate `from routes.process import process_routes`.

### ✅ Bug 6: Shell Injection in Nginx Config Writing (Fixed)
**File:** `routes/nginx.py` `write_nginx_config()`  
**Fix applied:** Replaced `echo '{content}' > {file_path}` with `subprocess.run(["sudo", "tee", file_path], input=content, text=True, ...)`.

### ✅ Bug 7: Zombie Event Listener (Fixed)
**File:** `app.py` `start_listening_for_events()`  
**Fix applied:** Replaced `subprocess.run(capture_output=True)` (blocking) with `subprocess.Popen(stdout=PIPE)` streaming.

---

## 🔒 Security Issues

### ✅ Issue 1: Hardcoded Admin Password (Fixed)
**File:** `app.py` `create_admin_user()`  
**Fix applied:** Uses `os.getenv('ADMIN_PASSWORD')` with fallback to `secrets.token_urlsafe(16)` (printed on first run).

### ✅ Issue 2: CSRF Protection Added
**Files:** `app.py`, `templates/layout.html`, all auth templates, schedule, nginx, git forms  
**Fix applied:**
- `CSRFProtect(app)` initialized in `app.py`
- Meta tag `<meta name="csrf-token">` added to `layout.html`
- Global JavaScript `fetch()` interceptor auto-attaches `X-CSRFToken` header to all non-GET requests
- Hidden `csrf_token` input added to all HTML `<form method="POST">` elements
- `Flask-WTF` added to `requirements.txt`

### ✅ Issue 3: Rate Limiting Added
**File:** `app.py`, `routes/auth.py`  
**Fix applied:** `Flask-Limiter` initialized with Redis storage backend. Auth blueprint rate-limited to 5 requests/minute.

### ✅ Issue 4: Weak Reset Tokens (Fixed)
**File:** `routes/auth.py`  
**Fix applied:** Replaced `generate_random_string(10)` with `secrets.token_urlsafe(32)` for password reset tokens.

### 🔧 Issue 5: Open Registration
**Description:** Anyone can register. *Not yet implemented — requires admin settings UI.*

---

## 🏗️ Architecture Improvements

### 🔧 1. Split `utils.py` (1608 lines)
*Not yet implemented — large refactor. The file should be split into `utils/docker.py`, `utils/email.py`, `utils/domain.py`, `utils/security.py`.*

### ✅ 2. Remove Subprocess Calls from Models
**Fix applied:** `models/process.py` `@property status` removed entirely. Model is now a pure data object.

### ✅ 3. Use Python `logging` Module
**File:** `app.py`  
**Fix applied:** `logging.basicConfig()` configured with logger instance. Key startup events now use `logger.info()`/`logger.error()`.

### 🔧 4. Add API Versioning
*Not yet implemented — would require route prefix changes.*

### 🔧 5. Standardize Error Responses
*Not yet implemented — would require touching all route handlers.*

### ✅ 6. Add Database Indexes
**File:** `models/process.py`  
**Fix applied:** Added `index=True` to `Process.name` and `Process.owner_id` columns.

### ✅ 7. Add Health Check Endpoint
**File:** `app.py`  
**Fix applied:** Added `/health` endpoint that checks database, Redis, and Docker daemon connectivity. Returns JSON with per-check status and HTTP 200 (ok) or 503 (degraded).

---

## 📊 Priority Matrix (Updated)

| Priority | Item | Status | Impact |
|----------|------|--------|--------|
| 🔴 P0 | Fix `os.chdir()` race condition | ✅ Done | Prevents random crashes |
| 🔴 P0 | Remove hardcoded admin password | ✅ Done | Security |
| 🔴 P0 | Add CSRF protection | ✅ Done | Security |
| 🟡 P1 | Remove subprocess from model property | ✅ Done | Performance + Architecture |
| 🟡 P1 | Cache `is_always_running_container()` | ✅ Done | Performance |
| 🟡 P1 | Switch to `docker compose` v2 | ✅ Done | Performance (2-5x speedup) |
| 🟡 P1 | Fix shell injection in nginx config | ✅ Done | Security |
| 🟡 P1 | Add rate limiting to auth | ✅ Done | Security |
| � P1 | Fix uptime calculation bug | ✅ Done | Correctness |
| 🟡 P1 | Redis-backed process cache | ✅ Done | Multi-worker consistency |
| 🟢 P2 | Reduce gunicorn workers to 6 | ✅ Done | Memory usage |
| 🟢 P2 | Use proper `logging` module | ✅ Done | Observability |
| 🟢 P2 | Zombie event listener fix | ✅ Done | Stability |
| 🟢 P2 | Split `utils.py` | 🔧 TODO | Maintainability |
| 🟢 P2 | Add tests | 🔧 TODO | Reliability |
| 🔵 P3 | WebSocket console | 🔧 TODO | UX + Performance |
| 🔵 P3 | API versioning | 🔧 TODO | Future-proofing |
| 🔵 P3 | Health check endpoint | ✅ Done | Operations |
