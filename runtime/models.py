"""Runtime state models for process supervisors."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class RuntimeState(str, Enum):
    CREATING = "CREATING"
    BUILDING = "BUILDING"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    RESTARTING = "RESTARTING"
    ERROR = "ERROR"


@dataclass
class ContainerStats:
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_mb: float = 0.0
    status: str = "stopped"


@dataclass
class ProcessRuntimeInfo:
    """In-memory runtime snapshot for a managed process."""

    process_name: str
    state: RuntimeState = RuntimeState.STOPPED
    container_id: Optional[str] = None
    always_running: bool = False
    process_type: Optional[str] = None
    stats: ContainerStats = field(default_factory=ContainerStats)
    metadata: dict[str, Any] = field(default_factory=dict)
