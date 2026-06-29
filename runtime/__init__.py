"""Server Manager runtime layer (Wings-inspired)."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any, Dict, Generator, Optional

from runtime.docker_runtime import DockerRuntime, stream_docker_events
from runtime.event_bus import EventBus, SyncEventQueue
from runtime.events import CONSOLE_EVENT_TYPES
from runtime.models import ContainerStats
from runtime.supervisor import ProcessSupervisor
from runtime.websocket import backlog_lines_to_sse, sse_generator

logger = logging.getLogger("server-manager.runtime")

_runtime: Optional["RuntimeManager"] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_thread: Optional[threading.Thread] = None


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop, _loop_thread
    if _loop is not None and _loop.is_running():
        return _loop

    _loop = asyncio.new_event_loop()

    def _run_loop() -> None:
        asyncio.set_event_loop(_loop)
        _loop.run_forever()

    _loop_thread = threading.Thread(target=_run_loop, name="runtime-async", daemon=True)
    _loop_thread.start()
    return _loop


def run_sync(coro, timeout: float = 300):
    """Run an async coroutine from synchronous Flask/gevent code."""
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


def reset_runtime_after_fork() -> None:
    """Reset asyncio runtime state after gunicorn worker fork (preload_app safe)."""
    global _runtime, _loop, _loop_thread
    _runtime = None
    if _loop is not None:
        try:
            _loop.call_soon_threadsafe(_loop.stop)
        except Exception:
            pass
    _loop = None
    _loop_thread = None


def claim_docker_events_listener(worker_pid: int) -> bool:
    """Only one gunicorn worker should subscribe to docker events in production."""
    if os.getenv("ENVIRONMENT") != "production":
        return True
    try:
        import redis

        client = redis.StrictRedis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            decode_responses=True,
        )
        return bool(
            client.set(
                "runtime_docker_events_lock",
                str(worker_pid),
                nx=True,
                ex=3600,
            )
        )
    except Exception as exc:
        logger.warning("Could not claim docker events lock: %s", exc)
        return False


def _verify_docker(runtime: "RuntimeManager") -> None:
    result = run_sync(
        runtime.docker.run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=15)
    )
    if result.success:
        logger.info("Docker available (server %s)", result.stdout.strip())
    else:
        logger.error(
            "Docker is not reachable from this process (PATH=%s): %s",
            os.getenv("PATH", ""),
            (result.stderr or result.stdout or "unknown error").strip(),
        )


def _metrics_status_from_display(display_status: str) -> str:
    normalized = (display_status or "").strip().lower()
    if normalized == "running":
        return "running"
    if normalized == "process stopped":
        return "process_stopped"
    if normalized == "restarting":
        return "restarting"
    return "stopped"


class RuntimeManager:
    """Owns supervisors, event bus, and docker runtime for the whole host."""

    def __init__(self, active_servers_dir: Optional[str] = None) -> None:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.active_servers_dir = active_servers_dir or os.path.join(
            base, "active-servers"
        )
        self.bus = EventBus()
        self.docker = DockerRuntime(self.active_servers_dir)
        self.supervisors: Dict[str, ProcessSupervisor] = {}
        self._docker_events_task: Optional[asyncio.Task] = None
        self._all_stats: Dict[str, Dict[str, float]] = {}
        self._started = False

    async def start_runtime(self, docker_events: bool = True) -> None:
        if self._started:
            return
        self._started = True
        await self.bus.subscribe_all(self._on_stats_event)
        if docker_events:
            self._docker_events_task = asyncio.create_task(
                self._docker_events_loop(), name="docker-events"
            )
        logger.info("Runtime manager started")

    async def stop_runtime(self) -> None:
        if self._docker_events_task:
            self._docker_events_task.cancel()
            try:
                await self._docker_events_task
            except asyncio.CancelledError:
                pass
        for supervisor in list(self.supervisors.values()):
            await supervisor.shutdown()
        self.supervisors.clear()
        self._started = False

    async def _on_stats_event(self, event: Any) -> None:
        from runtime.events import StatsUpdatedEvent

        if isinstance(event, StatsUpdatedEvent):
            self._all_stats[event.process_name] = {
                "cpu_percent": event.stats.cpu_percent,
                "memory_percent": event.stats.memory_percent,
                "memory_mb": event.stats.memory_mb,
            }

    async def _docker_events_loop(self) -> None:
        async for raw in stream_docker_events():
            try:
                name = ""
                actor = raw.get("Actor", {})
                attrs = actor.get("Attributes", {})
                raw_name = attrs.get("name", "")
                if raw_name:
                    name = raw_name.split("_")[0]
                if name and name in self.supervisors:
                    await self.supervisors[name].handle_docker_event(raw)
            except Exception as exc:
                logger.debug("docker event handling error: %s", exc)

    def get_supervisor(
        self,
        process_name: str,
        process_type: Optional[str] = None,
        create: bool = True,
    ) -> Optional[ProcessSupervisor]:
        if process_name not in self.supervisors and create:
            self.supervisors[process_name] = ProcessSupervisor(
                process_name,
                self.docker,
                self.bus,
                process_type=process_type,
            )
        sup = self.supervisors.get(process_name)
        if sup and process_type and not sup.info.process_type:
            sup.info.process_type = process_type
        return sup

    async def register_process(
        self, process_name: str, process_type: Optional[str] = None
    ) -> ProcessSupervisor:
        sup = self.get_supervisor(process_name, process_type=process_type)
        assert sup is not None
        if process_type:
            sup.info.process_type = process_type
        await sup.sync_state_from_docker()
        await sup.ensure_streams()
        return sup

    def unregister_process(self, process_name: str) -> None:
        run_sync(self._unregister_process(process_name))

    async def _unregister_process(self, process_name: str) -> None:
        await self.unregister_process_async(process_name)

    async def unregister_process_async(self, process_name: str) -> None:
        sup = self.supervisors.pop(process_name, None)
        if sup:
            await sup.shutdown()

    # --- Sync API for Flask routes ---

    def start(self, process_name: str, process_type: Optional[str] = None) -> Dict[str, Any]:
        return run_sync(self._start(process_name, process_type))

    async def _start(self, process_name: str, process_type: Optional[str] = None):
        sup = await self.register_process(process_name, process_type)
        return await sup.start()

    def stop(self, process_name: str, process_type: Optional[str] = None) -> Dict[str, Any]:
        return run_sync(self._stop(process_name, process_type))

    async def _stop(self, process_name: str, process_type: Optional[str] = None):
        sup = self.get_supervisor(process_name, process_type=process_type, create=True)
        assert sup is not None
        if process_type:
            sup.info.process_type = process_type
        await sup.refresh_metadata()
        await sup.ensure_streams()
        return await sup.stop()

    def restart(self, process_name: str, process_type: Optional[str] = None) -> Dict[str, Any]:
        return run_sync(self._restart(process_name, process_type))

    async def _restart(self, process_name: str, process_type: Optional[str] = None):
        sup = await self.register_process(process_name, process_type)
        return await sup.restart()

    def rebuild_async(self, process_name: str, process_type: Optional[str] = None) -> None:
        """Fire-and-forget rebuild on the runtime asyncio loop."""
        loop = _ensure_loop()
        asyncio.run_coroutine_threadsafe(
            self._rebuild(process_name, process_type), loop
        )

    async def _rebuild(self, process_name: str, process_type: Optional[str] = None):
        sup = await self.register_process(process_name, process_type)
        await sup.rebuild()

    def execute(
        self,
        process_name: str,
        command: str,
        working_dir: str = "/app",
        timeout: int = 30,
        process_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        return run_sync(
            self._execute(process_name, command, working_dir, timeout, process_type)
        )

    async def _execute(
        self,
        process_name: str,
        command: str,
        working_dir: str,
        timeout: int,
        process_type: Optional[str],
    ):
        sup = await self.register_process(process_name, process_type)
        return await sup.run_command(command, working_dir, timeout)

    def execute_interactive(
        self,
        process_name: str,
        command: str,
        working_dir: str = "/app",
        process_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        return run_sync(
            self._execute_interactive(process_name, command, working_dir, process_type)
        )

    async def _execute_interactive(
        self,
        process_name: str,
        command: str,
        working_dir: str,
        process_type: Optional[str],
    ):
        sup = await self.register_process(process_name, process_type)
        return await sup.run_interactive(command, working_dir)

    def clear_logs(self, process_name: str) -> Dict[str, Any]:
        return run_sync(self._clear_logs(process_name))

    async def _clear_logs(self, process_name: str):
        sup = await self.register_process(process_name)
        return await sup.clear_logs()

    def get_status(self, process_name: str, process_type: Optional[str] = None) -> Dict[str, Any]:
        return run_sync(self._get_status(process_name, process_type))

    async def _get_status(self, process_name: str, process_type: Optional[str] = None):
        sup = self.get_supervisor(process_name, process_type=process_type, create=True)
        assert sup is not None
        if process_type:
            sup.info.process_type = process_type
        await sup.refresh_metadata()
        return await sup.get_status_dict()

    def get_metrics(self, process_name: str, process_type: Optional[str] = None) -> Dict[str, Any]:
        return run_sync(self._get_metrics(process_name, process_type))

    async def _get_metrics(self, process_name: str, process_type: Optional[str] = None):
        sup = self.supervisors.get(process_name)
        if sup is None:
            sup = self.get_supervisor(process_name, process_type=process_type, create=True)
        if sup and process_type:
            sup.info.process_type = process_type

        status_dict = await sup.get_status_dict() if sup else {"status": "Exited"}
        display_status = status_dict.get("status", "Exited")
        metrics_status = _metrics_status_from_display(display_status)

        container_id = await self.docker.get_container_id(process_name)
        if not container_id or metrics_status == "stopped":
            return {
                "cpu_percent": 0,
                "memory_percent": 0,
                "memory_mb": 0,
                "status": metrics_status,
                "display_status": display_status,
            }

        raw = await self.docker.get_stats(container_id)
        return {
            **raw,
            "status": metrics_status,
            "display_status": display_status,
        }

    def get_all_metrics(self) -> Dict[str, Dict[str, float]]:
        if self._all_stats:
            return dict(self._all_stats)
        return run_sync(self.docker.get_all_stats())

    def get_container_id(self, process_name: str) -> Optional[str]:
        return run_sync(self.docker.get_container_id(process_name))

    def get_all_container_statuses(self) -> Dict[str, Dict[str, Any]]:
        return run_sync(self.docker.refresh_container_cache())

    def invalidate_docker_cache(self) -> None:
        self.docker.invalidate_cache()

    def compose_up(self, process_name: str) -> Dict[str, Any]:
        result = run_sync(self.docker.compose_up(process_name))
        self.docker.invalidate_cache()
        return {"success": result.success, "stderr": result.stderr}

    def compose_down(self, process_name: str) -> Dict[str, Any]:
        result = run_sync(self.docker.compose_down(process_name))
        return {"success": result.success, "stderr": result.stderr}

    def ensure_process(self, process_name: str, process_type: Optional[str] = None) -> None:
        """Register supervisor and start log/stats streams if needed."""
        run_sync(self.register_process(process_name, process_type))

    def subscribe_console(self, process_name: str, process_type: Optional[str] = None) -> Generator[str, None, None]:
        """SSE generator: backlog on connect while running, then live events from the bus."""
        self.ensure_process(process_name, process_type)

        sup = self.get_supervisor(process_name, process_type, create=False)
        if sup:
            status = run_sync(sup.get_status_dict()).get("status", "Exited")
            if status.lower() == "running":
                backlog = run_sync(sup.log_stream.fetch_backlog_lines())
                yield from backlog_lines_to_sse(backlog)

        queue = self.bus.subscribe_sync_queue(process_name, set(CONSOLE_EVENT_TYPES))
        run_sync(queue.register())
        try:
            yield from sse_generator(queue)
        finally:
            run_sync(queue.unregister())

    def is_always_running(self, process_name: str) -> bool:
        return run_sync(self.docker.is_always_running(process_name))

    def get_uptime_started_at(self, process_name: str) -> Optional[str]:
        cid = run_sync(self.docker.get_container_id(process_name))
        if not cid:
            return None
        return run_sync(self.docker.inspect_started_at(cid))


def get_runtime() -> RuntimeManager:
    global _runtime
    if _runtime is None:
        _runtime = RuntimeManager()
    return _runtime


def init_runtime(app=None, load_processes: bool = True, docker_events: bool = True) -> RuntimeManager:
    """Initialize runtime on application startup."""
    runtime = get_runtime()
    _verify_docker(runtime)
    run_sync(runtime.start_runtime(docker_events=docker_events))

    if load_processes and app is not None:
        with app.app_context():
            try:
                from models.process import Process

                processes = Process.query.all()
                logger.info("Preloading %d process supervisor(s)", len(processes))
                for process in processes:
                    run_sync(
                        runtime.register_process(process.name, process.type),
                        timeout=60,
                    )
            except Exception as exc:
                logger.exception("Could not preload process supervisors: %s", exc)

    return runtime
