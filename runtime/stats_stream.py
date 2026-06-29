"""Periodic container stats collection."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from runtime.docker_runtime import DockerRuntime
from runtime.event_bus import EventBus
from runtime.events import StatsUpdatedEvent
from runtime.models import ContainerStats

logger = logging.getLogger("server-manager.runtime.stats_stream")


class StatsStream:
    def __init__(
        self,
        process_name: str,
        docker: DockerRuntime,
        bus: EventBus,
        interval: float = 3.0,
    ) -> None:
        self.process_name = process_name
        self.docker = docker
        self.bus = bus
        self.interval = interval
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.latest = ContainerStats()

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f"stats-{self.process_name}")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while self._running:
            try:
                container_id = await self.docker.get_container_id(self.process_name)
                if not container_id:
                    self.latest = ContainerStats(status="stopped")
                else:
                    raw = await self.docker.get_stats(container_id)
                    metrics_status = "running"
                    always_running = await self.docker.is_always_running(self.process_name)
                    if always_running:
                        from runtime.lifecycle import check_inner_process_running

                        inner = await check_inner_process_running(
                            self.docker, self.process_name
                        )
                        if not inner.get("process_running"):
                            metrics_status = "process_stopped"
                    self.latest = ContainerStats(
                        cpu_percent=raw.get("cpu_percent", 0.0),
                        memory_percent=raw.get("memory_percent", 0.0),
                        memory_mb=raw.get("memory_mb", 0.0),
                        status=metrics_status,
                    )
                await self.bus.publish(
                    StatsUpdatedEvent(process_name=self.process_name, stats=self.latest)
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("Stats collection failed for %s: %s", self.process_name, exc)

            await asyncio.sleep(self.interval)
