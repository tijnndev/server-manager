"""Strongly typed runtime events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from runtime.models import ContainerStats, RuntimeState


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class BaseEvent:
    process_name: str
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class ConsoleOutputEvent(BaseEvent):
    line: str = ""
    source: str = "stdout"  # stdout | stderr | system | build


@dataclass(frozen=True)
class ContainerCreatedEvent(BaseEvent):
    container_id: Optional[str] = None


@dataclass(frozen=True)
class ContainerStartedEvent(BaseEvent):
    container_id: Optional[str] = None


@dataclass(frozen=True)
class ContainerStoppedEvent(BaseEvent):
    container_id: Optional[str] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class ContainerRemovedEvent(BaseEvent):
    container_id: Optional[str] = None


@dataclass(frozen=True)
class ContainerDiedEvent(BaseEvent):
    container_id: Optional[str] = None
    exit_code: Optional[int] = None


@dataclass(frozen=True)
class ImagePulledEvent(BaseEvent):
    image: str = ""


@dataclass(frozen=True)
class StatsUpdatedEvent(BaseEvent):
    stats: ContainerStats = field(default_factory=ContainerStats)


@dataclass(frozen=True)
class StateChangedEvent(BaseEvent):
    old_state: RuntimeState = RuntimeState.STOPPED
    new_state: RuntimeState = RuntimeState.STOPPED


@dataclass(frozen=True)
class BuildStartedEvent(BaseEvent):
    pass


@dataclass(frozen=True)
class BuildOutputEvent(BaseEvent):
    line: str = ""


@dataclass(frozen=True)
class BuildFinishedEvent(BaseEvent):
    success: bool = True
    message: str = ""


@dataclass(frozen=True)
class PowerActionEvent(BaseEvent):
    action: str = ""  # start | stop | restart | rebuild
    success: bool = True
    details: Optional[str] = None


@dataclass(frozen=True)
class CommandExecutedEvent(BaseEvent):
    command: str = ""
    success: bool = True
    stdout: str = ""
    stderr: str = ""
    return_code: int = 0
    error: Optional[str] = None


@dataclass(frozen=True)
class ErrorEvent(BaseEvent):
    message: str = ""
    source: str = ""
    details: Optional[Any] = None


# Event types that SSE clients typically care about
CONSOLE_EVENT_TYPES = (
    ConsoleOutputEvent,
    BuildOutputEvent,
)
