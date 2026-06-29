"""Per-process log streaming with backlog + continuous follow."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from runtime.docker_runtime import DockerRuntime
from runtime.event_bus import EventBus
from runtime.events import ConsoleOutputEvent

logger = logging.getLogger("server-manager.runtime.log_stream")


class LogStream:
    """Attach to container/process output and publish ConsoleOutputEvent."""

    def __init__(
        self,
        process_name: str,
        docker: DockerRuntime,
        bus: EventBus,
        always_running: bool = False,
    ) -> None:
        self.process_name = process_name
        self.docker = docker
        self.bus = bus
        self.always_running = always_running
        self._task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def log_file(self) -> str:
        return f"/tmp/{self.process_name}_process.log"

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f"log-{self.process_name}")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def publish_line(self, line: str, source: str = "stdout") -> None:
        await self.bus.publish(
            ConsoleOutputEvent(
                process_name=self.process_name,
                line=line,
                source=source,
            )
        )

    async def fetch_backlog_lines(self, tail: int = 150) -> list[str]:
        """Read historical log lines for a new console subscriber (running processes only)."""
        lines: list[str] = []
        always_running = await self.docker.is_always_running(self.process_name)

        if always_running:
            container_id = await self.docker.get_container_id(self.process_name)
            if container_id:
                for line in await self.docker.compose_logs_backlog(
                    self.process_name, tail=tail
                ):
                    if line.strip():
                        lines.append(line)
                for line in await self.docker.exec_read_file(
                    container_id, self.log_file, tail=tail
                ):
                    if line.strip():
                        lines.append(line)
        else:
            for line in await self.docker.compose_logs_backlog(
                self.process_name, tail=tail
            ):
                if line.strip():
                    lines.append(line)
        return lines

    async def _run(self) -> None:
        try:
            if self.always_running:
                await self._stream_always_running()
            else:
                await self._stream_compose_logs()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("LogStream error for %s: %s", self.process_name, exc)

    async def _stream_compose_logs(self) -> None:
        process_dir = self.docker.process_dir(self.process_name)
        cmd = [
            "docker",
            "compose",
            "logs",
            "--tail",
            "50",
            "--follow",
            "--no-log-prefix",
            "--timestamps",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=process_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            while self._running and proc.stdout:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\n")
                if text.strip():
                    await self.publish_line(text)
        finally:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()

    async def _stream_always_running(self) -> None:
        while self._running:
            container_id = await self.docker.get_container_id(self.process_name)
            if not container_id:
                await asyncio.sleep(2)
                continue

            proc = await asyncio.create_subprocess_exec(
                "docker",
                "exec",
                container_id,
                "tail",
                "-n",
                "150",
                "-f",
                self.log_file,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                while self._running and proc.stdout:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").rstrip("\n")
                    if text.strip():
                        await self.publish_line(text)
            finally:
                if proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        proc.kill()

            if self._running:
                await asyncio.sleep(1)
