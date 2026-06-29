"""Per-process supervisor owning lifecycle, streams, and state."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from runtime.docker_runtime import DockerRuntime
from runtime.event_bus import EventBus
from runtime.events import (
    BuildFinishedEvent,
    BuildOutputEvent,
    BuildStartedEvent,
    CommandExecutedEvent,
    ConsoleOutputEvent,
    ContainerDiedEvent,
    ContainerRemovedEvent,
    ContainerStartedEvent,
    ContainerStoppedEvent,
    ErrorEvent,
    PowerActionEvent,
    StateChangedEvent,
)
from runtime.lifecycle import (
    check_inner_process_running,
    execute_command,
    execute_interactive,
    start_inner_process,
    stop_inner_process,
)
from runtime.log_stream import LogStream
from runtime.models import ProcessRuntimeInfo, RuntimeState
from runtime.stats_stream import StatsStream

logger = logging.getLogger("server-manager.runtime.supervisor")


class ProcessSupervisor:
    def __init__(
        self,
        process_name: str,
        docker: DockerRuntime,
        bus: EventBus,
        process_type: Optional[str] = None,
        stats_interval: float = 3.0,
    ) -> None:
        self.process_name = process_name
        self.docker = docker
        self.bus = bus
        self.info = ProcessRuntimeInfo(
            process_name=process_name,
            process_type=process_type,
        )
        self.log_stream = LogStream(process_name, docker, bus)
        self.stats_stream = StatsStream(
            process_name, docker, bus, interval=stats_interval
        )
        self._streams_started = False

    @property
    def state(self) -> RuntimeState:
        return self.info.state

    async def _set_state(self, new_state: RuntimeState) -> None:
        old = self.info.state
        if old == new_state:
            return
        self.info.state = new_state
        await self.bus.publish(
            StateChangedEvent(
                process_name=self.process_name,
                old_state=old,
                new_state=new_state,
            )
        )

    async def ensure_streams(self) -> None:
        if self._streams_started:
            return
        self.info.always_running = await self.docker.is_always_running(self.process_name)
        self.log_stream.always_running = self.info.always_running
        await self.log_stream.start()
        await self.stats_stream.start()
        self._streams_started = True

    async def shutdown(self) -> None:
        await self.log_stream.stop()
        await self.stats_stream.stop()
        self._streams_started = False

    async def refresh_metadata(self) -> None:
        cid = await self.docker.get_container_id(self.process_name)
        self.info.container_id = cid
        self.info.always_running = await self.docker.is_always_running(self.process_name)
        self.log_stream.always_running = self.info.always_running

    async def sync_state_from_docker(self) -> None:
        """Align supervisor state with actual Docker / in-container process state."""
        if self.info.state in (
            RuntimeState.STARTING,
            RuntimeState.STOPPING,
            RuntimeState.RESTARTING,
            RuntimeState.BUILDING,
        ):
            return

        await self.refresh_metadata()

        if not self.info.container_id:
            await self._set_state(RuntimeState.STOPPED)
            return

        docker_state = await self.docker.inspect_state(self.info.container_id)
        if docker_state != "running":
            await self._set_state(RuntimeState.STOPPED)
            return

        if self.info.always_running and self.info.process_type != "python":
            inner = await check_inner_process_running(self.docker, self.process_name)
            if inner.get("process_running"):
                await self._set_state(RuntimeState.RUNNING)
            else:
                await self._set_state(RuntimeState.STOPPED)
        else:
            await self._set_state(RuntimeState.RUNNING)

    async def resolve_display_status(self) -> str:
        """Return the status string shown in the web UI."""
        await self.refresh_metadata()

        if not self.info.container_id:
            return "Exited"

        cache = await self.docker.refresh_container_cache()
        entry = cache.get(self.process_name)
        if not entry:
            return "Exited"

        state = entry["state"]
        if state == "running":
            if self.info.always_running and self.info.process_type != "python":
                inner = await check_inner_process_running(self.docker, self.process_name)
                return inner.get("status", "Running")
            return "Running"
        if state == "restarting":
            return "Restarting"
        return "Exited"

    async def get_status_dict(self) -> Dict[str, Any]:
        status = await self.resolve_display_status()
        return {"process": self.process_name, "status": status}

    async def start(self) -> Dict[str, Any]:
        await self.refresh_metadata()
        self.log_stream.always_running = self.info.always_running
        await self.ensure_streams()
        await self._set_state(RuntimeState.STARTING)
        try:
            if self.info.always_running:
                result = await start_inner_process(self.docker, self.process_name)
            else:
                result_raw = await self.docker.compose_up(self.process_name)
                result = {
                    "success": result_raw.success,
                    "message": f"Process '{self.process_name}' started successfully.",
                    "error": result_raw.stderr,
                }
                if result_raw.success:
                    await asyncio.sleep(2)

            if result.get("success"):
                await self.refresh_metadata()
                await self._set_state(RuntimeState.RUNNING)
                await self.bus.publish(
                    PowerActionEvent(
                        process_name=self.process_name,
                        action="start",
                        success=True,
                    )
                )
                await self.bus.publish(
                    ContainerStartedEvent(
                        process_name=self.process_name,
                        container_id=self.info.container_id,
                    )
                )
            else:
                await self._set_state(RuntimeState.ERROR)
                await self.bus.publish(
                    PowerActionEvent(
                        process_name=self.process_name,
                        action="start",
                        success=False,
                        details=result.get("error"),
                    )
                )
            return result
        except Exception as exc:
            await self._set_state(RuntimeState.ERROR)
            await self.bus.publish(
                ErrorEvent(
                    process_name=self.process_name,
                    message=str(exc),
                    source="start",
                )
            )
            return {"success": False, "error": str(exc)}

    async def stop(self) -> Dict[str, Any]:
        await self.refresh_metadata()
        self.log_stream.always_running = self.info.always_running
        await self.ensure_streams()
        await self._set_state(RuntimeState.STOPPING)
        try:
            if self.info.always_running:
                result = await stop_inner_process(self.docker, self.process_name)
            else:
                result_raw = await self.docker.compose_stop(self.process_name)
                result = {
                    "success": result_raw.success,
                    "message": f"Process {self.process_name} stopped successfully.",
                    "error": result_raw.stderr,
                }

            if result.get("success"):
                self.docker.invalidate_cache()
                await self._set_state(RuntimeState.STOPPED)
                await self.bus.publish(
                    PowerActionEvent(
                        process_name=self.process_name,
                        action="stop",
                        success=True,
                    )
                )
                await self.bus.publish(
                    ContainerStoppedEvent(
                        process_name=self.process_name,
                        container_id=self.info.container_id,
                    )
                )
            else:
                await self._set_state(RuntimeState.ERROR)
            return result
        except Exception as exc:
            await self._set_state(RuntimeState.ERROR)
            return {"success": False, "error": str(exc)}

    async def restart(self) -> Dict[str, Any]:
        await self.refresh_metadata()
        self.log_stream.always_running = self.info.always_running
        await self._set_state(RuntimeState.RESTARTING)
        if self.info.always_running:
            stop_result = await self.stop()
            if not stop_result.get("success"):
                return stop_result
            return await self.start()
        result_raw = await self.docker.compose_restart(self.process_name)
        if result_raw.success:
            await self.refresh_metadata()
            await self._set_state(RuntimeState.RUNNING)
            await self.bus.publish(
                PowerActionEvent(
                    process_name=self.process_name,
                    action="restart",
                    success=True,
                )
            )
            return {
                "success": True,
                "message": f"Process '{self.process_name}' restarted successfully.",
            }
        await self._set_state(RuntimeState.ERROR)
        return {"success": False, "error": result_raw.stderr}

    async def rebuild(self) -> None:
        await self.ensure_streams()
        await self._set_state(RuntimeState.BUILDING)
        await self.bus.publish(BuildStartedEvent(process_name=self.process_name))
        try:
            await self.docker.compose_down(self.process_name)
            async for line in self.docker.compose_build(self.process_name):
                colored = line
                await self.bus.publish(
                    BuildOutputEvent(process_name=self.process_name, line=colored)
                )
                await self.bus.publish(
                    ConsoleOutputEvent(
                        process_name=self.process_name,
                        line=colored,
                        source="build",
                    )
                )
            await self.bus.publish(
                BuildFinishedEvent(
                    process_name=self.process_name,
                    success=True,
                    message="Build process finished.",
                )
            )
            await self.bus.publish(
                ConsoleOutputEvent(
                    process_name=self.process_name,
                    line="[rebuild] Build process finished.",
                    source="build",
                )
            )
            await self._set_state(RuntimeState.STOPPED)
        except Exception as exc:
            await self.bus.publish(
                BuildFinishedEvent(
                    process_name=self.process_name,
                    success=False,
                    message=str(exc),
                )
            )
            await self.bus.publish(
                ConsoleOutputEvent(
                    process_name=self.process_name,
                    line=f"[rebuild error] {exc}",
                    source="build",
                )
            )
            await self._set_state(RuntimeState.ERROR)

    async def remove(self) -> None:
        await self.docker.compose_down(self.process_name)
        await self.shutdown()
        await self.bus.publish(
            ContainerRemovedEvent(
                process_name=self.process_name,
                container_id=self.info.container_id,
            )
        )
        await self._set_state(RuntimeState.STOPPED)

    async def run_command(
        self,
        command: str,
        working_dir: str = "/app",
        timeout: int = 30,
    ) -> Dict[str, Any]:
        await self.ensure_streams()
        result = await execute_command(
            self.docker,
            self.process_name,
            command,
            working_dir,
            timeout,
            process_type=self.info.process_type,
        )
        await self.bus.publish(
            CommandExecutedEvent(
                process_name=self.process_name,
                command=command,
                success=result.get("success", False),
                stdout=result.get("stdout", ""),
                stderr=result.get("stderr", ""),
                return_code=result.get("return_code", 0),
                error=result.get("error"),
            )
        )
        if result.get("success"):
            if result.get("stdout"):
                for line in result["stdout"].split("\n"):
                    if line.strip():
                        await self.log_stream.publish_line(line)
            if result.get("stderr"):
                for line in result["stderr"].split("\n"):
                    if line.strip():
                        await self.log_stream.publish_line(f"[ERROR] {line}", source="stderr")
        else:
            await self.log_stream.publish_line(
                f"[ERROR] {result.get('error', 'Command failed')}",
                source="stderr",
            )
        return result

    async def run_interactive(
        self, command: str, working_dir: str = "/app"
    ) -> Dict[str, Any]:
        await self.ensure_streams()
        result = await execute_interactive(
            self.docker, self.process_name, command, working_dir
        )
        if result.get("success"):
            await self.log_stream.publish_line(
                f"Starting interactive: {command}", source="system"
            )
            proc = result.get("process")
            if proc:
                await self.log_stream.publish_line(
                    f"Interactive command started (PID: {proc.pid})",
                    source="system",
                )
        else:
            await self.log_stream.publish_line(
                f"[ERROR] Failed to start interactive command: {result.get('error')}",
                source="stderr",
            )
        return result

    async def clear_logs(self) -> Dict[str, Any]:
        log_file = self.log_stream.log_file
        result = await self.docker.clear_process_log(self.process_name, log_file)
        if result.success:
            await self.log_stream.publish_line("===== LOGS CLEARED =====", source="system")
            return {"success": True, "message": "Logs cleared successfully"}
        return {"success": False, "error": "Failed to clear logs"}

    async def handle_docker_event(self, event: dict) -> None:
        if event.get("Type") != "container":
            return
        action = event.get("Action", "")
        actor = event.get("Actor", {})
        attrs = actor.get("Attributes", {})
        raw_name = attrs.get("name", "")
        name = raw_name.split("_")[0] if raw_name else ""
        if name != self.process_name:
            return

        cid = actor.get("ID")
        if action in ("start", "restart"):
            self.info.container_id = cid
            await self.sync_state_from_docker()
            if self.info.state == RuntimeState.RUNNING:
                await self.bus.publish(
                    ContainerStartedEvent(process_name=self.process_name, container_id=cid)
                )
        elif action in ("stop", "pause"):
            await self._set_state(RuntimeState.STOPPED)
            await self.bus.publish(
                ContainerStoppedEvent(process_name=self.process_name, container_id=cid)
            )
        elif action == "die":
            await self._set_state(RuntimeState.STOPPED)
            await self.bus.publish(
                ContainerDiedEvent(process_name=self.process_name, container_id=cid)
            )
        elif action == "destroy":
            await self.bus.publish(
                ContainerRemovedEvent(process_name=self.process_name, container_id=cid)
            )
