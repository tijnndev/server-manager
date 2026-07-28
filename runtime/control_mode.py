"""Stable control-mode resolution (inner process vs compose).

Mode must not flip solely because a container is currently missing.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from runtime.docker_runtime import DockerRuntime

logger = logging.getLogger("server-manager.runtime.control_mode")

# Keep-alive container + MAIN_COMMAND controlled via docker exec
INNER_TYPES = frozenset({"nodejs", "python", "php", "go", "nginx", "mariadb"})

# Container itself is the managed process
COMPOSE_TYPES = frozenset({"minecraft", "vite"})


def _compose_file_path(active_servers_dir: str, process_name: str) -> Optional[str]:
    process_dir = os.path.join(active_servers_dir, process_name)
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        path = os.path.join(process_dir, name)
        if os.path.isfile(path):
            return path
    return None


def always_running_from_compose_file(
    active_servers_dir: str, process_name: str
) -> Optional[bool]:
    """Infer mode from compose file contents. None if file missing / inconclusive."""
    path = _compose_file_path(active_servers_dir, process_name)
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        logger.debug("Could not read compose for %s: %s", process_name, exc)
        return None

    if "MAIN_COMMAND=" in text or "MAIN_COMMAND:" in text:
        return True
    if "tail" in text and "/dev/null" in text:
        return True
    return False


def always_running_from_process_type(process_type: Optional[str]) -> Optional[bool]:
    if not process_type:
        return None
    pt = process_type.strip().lower()
    if pt in INNER_TYPES:
        return True
    if pt in COMPOSE_TYPES:
        return False
    return None


async def resolve_always_running(
    docker: DockerRuntime,
    process_name: str,
    process_type: Optional[str] = None,
) -> bool:
    """Resolve whether this process uses inner-process control.

    Order: process type → compose file → live container MAIN_COMMAND (last resort).
    Missing container alone never forces compose mode when type/compose say inner.
    """
    from_type = always_running_from_process_type(process_type)
    if from_type is not None:
        return from_type

    from_compose = always_running_from_compose_file(
        docker.active_servers_dir, process_name
    )
    if from_compose is not None:
        return from_compose

    container_id = await docker.get_container_id(process_name)
    if not container_id:
        return False
    main_cmd = await docker.inspect_main_command(container_id)
    return main_cmd is not None
