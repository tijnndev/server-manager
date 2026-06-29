"""Centralized Docker operations (subprocess-based, SDK-swappable later)."""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import subprocess
import textwrap
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

logger = logging.getLogger("server-manager.runtime.docker")


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.returncode == 0


class DockerRuntime:
    """All Docker CLI interaction goes through this class."""

    def __init__(self, active_servers_dir: str) -> None:
        self.active_servers_dir = active_servers_dir
        self._container_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamp: float = 0.0
        self._cache_ttl: float = 3.0

    def process_dir(self, process_name: str) -> str:
        return os.path.join(self.active_servers_dir, process_name)

    async def run(
        self,
        cmd: List[str],
        cwd: Optional[str] = None,
        timeout: int = 120,
        check: bool = False,
    ) -> CommandResult:
        # Runs on the dedicated runtime asyncio thread; blocking is intentional
        # (asyncio.to_thread breaks under gevent workers).
        return self._run_sync(cmd, cwd, timeout, check)

    def _run_sync(
        self,
        cmd: List[str],
        cwd: Optional[str],
        timeout: int,
        check: bool,
    ) -> CommandResult:
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=check,
            )
            return CommandResult(result.returncode, result.stdout, result.stderr)
        except subprocess.CalledProcessError as exc:
            return CommandResult(
                exc.returncode,
                exc.stdout or "",
                exc.stderr or str(exc),
            )
        except subprocess.TimeoutExpired:
            return CommandResult(-1, "", f"Command timed out after {timeout}s")
        except Exception as exc:
            return CommandResult(-1, "", str(exc))

    async def popen_stream(
        self,
        cmd: List[str],
        cwd: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Stream line-by-line stdout from a long-running docker command."""

        def _iter_lines():
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            try:
                if proc.stdout:
                    for line in iter(proc.stdout.readline, ""):
                        if line:
                            yield line.rstrip("\n")
                proc.wait()
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()

        for line in _iter_lines():
            yield line

    async def refresh_container_cache(self, force: bool = False) -> Dict[str, Dict[str, Any]]:
        import time

        now = time.time()
        if not force and self._container_cache and now - self._cache_timestamp < self._cache_ttl:
            return self._container_cache

        result = await self.run(
            [
                "docker",
                "ps",
                "-a",
                "--format",
                '{{.ID}}|{{.Names}}|{{.State}}|{{.Status}}|{{.Label "com.docker.compose.service"}}',
            ],
            timeout=15,
        )
        containers: Dict[str, Dict[str, Any]] = {}
        if result.success:
            for line in result.stdout.strip().splitlines():
                if not line.strip():
                    continue
                parts = line.split("|", 4)
                if len(parts) < 3:
                    continue
                cid, name, state = parts[0], parts[1], parts[2]
                status_text = parts[3] if len(parts) > 3 else state
                service_name = parts[4].strip() if len(parts) > 4 else ""
                entry = {"id": cid, "state": state, "status": status_text}
                containers[name] = entry
                if service_name:
                    containers[service_name] = entry

        self._container_cache = containers
        self._cache_timestamp = now
        return containers

    def invalidate_cache(self) -> None:
        self._cache_timestamp = 0.0

    async def get_container_id(self, process_name: str) -> Optional[str]:
        cache = await self.refresh_container_cache()
        info = cache.get(process_name)
        if info:
            return info["id"]
        process_dir = self.process_dir(process_name)
        result = await self.run(
            ["docker", "compose", "ps", "-q", process_name],
            cwd=process_dir,
            timeout=15,
        )
        cid = result.stdout.strip()
        return cid or None

    async def compose_up(self, process_name: str, detach: bool = True) -> CommandResult:
        self.invalidate_cache()
        cmd = ["docker", "compose", "up"]
        if detach:
            cmd.append("-d")
        return await self.run(cmd, cwd=self.process_dir(process_name), timeout=600)

    async def compose_down(self, process_name: str) -> CommandResult:
        self.invalidate_cache()
        return await self.run(
            ["docker", "compose", "down"],
            cwd=self.process_dir(process_name),
            timeout=120,
        )

    async def compose_stop(self, process_name: str) -> CommandResult:
        self.invalidate_cache()
        return await self.run(
            ["docker", "compose", "stop"],
            cwd=self.process_dir(process_name),
            timeout=60,
        )

    async def compose_restart(self, process_name: str) -> CommandResult:
        self.invalidate_cache()
        return await self.run(
            ["docker", "compose", "restart"],
            cwd=self.process_dir(process_name),
            timeout=120,
        )

    async def compose_build(self, process_name: str) -> AsyncIterator[str]:
        process_dir = self.process_dir(process_name)
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "compose",
            "build",
            cwd=process_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            while proc.stdout:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\n")
                if text:
                    yield text
        finally:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10)
                except asyncio.TimeoutError:
                    proc.kill()

    async def compose_logs_backlog(
        self,
        process_name: str,
        tail: int = 150,
        timestamps: bool = True,
    ) -> List[str]:
        cmd = ["docker", "compose", "logs", "--tail", str(tail), "--no-log-prefix"]
        if timestamps:
            cmd.append("--timestamps")
        result = await self.run(cmd, cwd=self.process_dir(process_name), timeout=30)
        if not result.success:
            return []
        return [ln for ln in result.stdout.splitlines() if ln.strip()]

    async def inspect_state(self, container_id: str) -> str:
        result = await self.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", container_id],
            timeout=10,
        )
        return result.stdout.strip() if result.success else ""

    async def inspect_started_at(self, container_id: str) -> str:
        result = await self.run(
            ["docker", "inspect", "--format", "{{.State.StartedAt}}", container_id],
            timeout=10,
        )
        return result.stdout.strip() if result.success else ""

    async def inspect_main_command(self, container_id: str) -> Optional[str]:
        result = await self.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{range .Config.Env}}{{println .}}{{end}}",
                container_id,
            ],
            timeout=10,
        )
        if not result.success:
            return None
        for line in result.stdout.splitlines():
            if line.startswith("MAIN_COMMAND="):
                return line.split("=", 1)[1].strip('"')
        return None

    async def get_process_pid(self, container_id: str, command: str) -> Optional[int]:
        if not container_id or not command:
            return None
        search_expr = shlex.quote(command)
        shell_cmd = (
            f"ps -eo pid,args | grep -F {search_expr} | grep -v grep | "
            "awk '{print $1}' | head -n 1"
        )
        result = await self.exec_in_container(container_id, shell_cmd, timeout=15)
        if result.success:
            pid = result.stdout.strip()
            return int(pid) if pid.isdigit() else None
        return None

    async def is_always_running(self, process_name: str) -> bool:
        container_id = await self.get_container_id(process_name)
        if not container_id:
            return False
        main_cmd = await self.inspect_main_command(container_id)
        return main_cmd is not None

    async def exec_in_container(
        self,
        container_id: str,
        shell_cmd: str,
        timeout: int = 30,
    ) -> CommandResult:
        return await self.run(
            ["docker", "exec", container_id, "sh", "-c", shell_cmd],
            timeout=timeout,
        )

    async def exec_read_file(
        self,
        container_id: str,
        path: str,
        tail: int = 150,
    ) -> List[str]:
        result = await self.exec_in_container(
            container_id,
            f"tail -n {tail} {shlex.quote(path)} 2>/dev/null || true",
            timeout=15,
        )
        if not result.stdout:
            return []
        return [ln for ln in result.stdout.splitlines() if ln.strip()]

    async def ensure_process_log_file(self, container_id: str, log_file: str) -> CommandResult:
        return await self.exec_in_container(
            container_id,
            f"touch {shlex.quote(log_file)}",
            timeout=10,
        )

    async def clear_process_log(self, process_name: str, log_file: str) -> CommandResult:
        container_id = await self.get_container_id(process_name)
        if not container_id:
            return CommandResult(1, "", "Container is not running")
        quoted = shlex.quote(log_file)
        return await self.exec_in_container(
            container_id,
            f"touch {quoted} && : > {quoted}",
            timeout=10,
        )

    async def get_stats(self, container_id: str) -> Dict[str, float]:
        result = await self.run(
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{.CPUPerc}}|{{.MemPerc}}|{{.MemUsage}}",
                container_id,
            ],
            timeout=10,
        )
        if not result.success or not result.stdout.strip():
            return {"cpu_percent": 0.0, "memory_percent": 0.0, "memory_mb": 0.0}

        parts = result.stdout.strip().split("|")
        cpu = float(parts[0].replace("%", "").strip() or 0)
        mem = float(parts[1].replace("%", "").strip() or 0)
        mem_usage = parts[2].split("/")[0].strip() if len(parts) > 2 else ""
        memory_mb = _parse_memory_mb(mem_usage)
        return {
            "cpu_percent": round(cpu, 2),
            "memory_percent": round(mem, 2),
            "memory_mb": round(memory_mb, 2),
        }

    async def get_all_stats(self) -> Dict[str, Dict[str, float]]:
        cache = await self.refresh_container_cache()
        result = await self.run(
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{.Name}}|{{.CPUPerc}}|{{.MemPerc}}|{{.MemUsage}}",
            ],
            timeout=20,
        )
        stats: Dict[str, Dict[str, float]] = {}
        if not result.success:
            return stats

        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue
            parts = line.split("|", 3)
            if len(parts) < 3:
                continue
            name = parts[0]
            cpu = float(parts[1].replace("%", "").strip() or 0)
            mem = float(parts[2].replace("%", "").strip() or 0)
            mem_usage = parts[3].split("/")[0].strip() if len(parts) > 3 else ""
            entry = {
                "cpu_percent": round(cpu, 2),
                "memory_percent": round(mem, 2),
                "memory_mb": round(_parse_memory_mb(mem_usage), 2),
            }
            stats[name] = entry
            if name in cache:
                cid = cache[name]["id"]
                for key, val in cache.items():
                    if val["id"] == cid and key != name:
                        stats[key] = entry
        return stats

    async def stream_compose_logs(
        self,
        process_name: str,
        tail: int = 50,
        timestamps: bool = True,
    ) -> AsyncIterator[str]:
        cmd = ["docker", "compose", "logs", "--tail", str(tail), "--follow", "--no-log-prefix"]
        if timestamps:
            cmd.append("--timestamps")

        queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

        def _reader():
            proc = subprocess.Popen(
                cmd,
                cwd=self.process_dir(process_name),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            try:
                if proc.stdout:
                    for line in iter(proc.stdout.readline, ""):
                        asyncio.get_event_loop().call_soon_threadsafe(
                            queue.put_nowait, line.rstrip("\n")
                        )
            finally:
                asyncio.get_event_loop().call_soon_threadsafe(queue.put_nowait, None)
                if proc.poll() is None:
                    proc.terminate()

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _reader)

        while True:
            line = await queue.get()
            if line is None:
                break
            if line.strip():
                yield line

    async def stream_exec_tail(
        self,
        container_id: str,
        path: str,
        tail: int = 150,
    ) -> AsyncIterator[str]:
        cmd = ["docker", "exec", container_id, "tail", "-n", str(tail), "-f", path]
        queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

        def _reader():
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            try:
                if proc.stdout:
                    for line in iter(proc.stdout.readline, ""):
                        asyncio.get_event_loop().call_soon_threadsafe(
                            queue.put_nowait, line.rstrip("\n")
                        )
            finally:
                asyncio.get_event_loop().call_soon_threadsafe(queue.put_nowait, None)
                if proc.poll() is None:
                    proc.terminate()

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _reader)

        while True:
            line = await queue.get()
            if line is None:
                break
            if line.strip():
                yield line


def _parse_memory_mb(mem_usage: str) -> float:
    if not mem_usage:
        return 0.0
    if "GiB" in mem_usage:
        return float(mem_usage.replace("GiB", "").strip()) * 1024
    if "MiB" in mem_usage:
        return float(mem_usage.replace("MiB", "").strip())
    if "KiB" in mem_usage:
        return float(mem_usage.replace("KiB", "").strip()) / 1024
    if "B" in mem_usage and "iB" not in mem_usage:
        return float(mem_usage.replace("B", "").strip()) / (1024 * 1024)
    return 0.0


async def stream_docker_events() -> AsyncIterator[dict]:
    """Continuously stream `docker events` JSON lines."""
    import json

    while True:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "events",
            "--format",
            "{{json .}}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            if proc.stdout:
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").strip()
                    if text:
                        try:
                            yield json.loads(text)
                        except json.JSONDecodeError:
                            continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("docker events stream error: %s", exc)
        finally:
            if proc.returncode is None:
                proc.terminate()
        await asyncio.sleep(5)
