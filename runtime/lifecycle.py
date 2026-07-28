"""In-container process lifecycle (always-running container mode)."""

from __future__ import annotations

import asyncio
import base64
import logging
import shlex
import textwrap
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from runtime.docker_runtime import CommandResult, DockerRuntime

logger = logging.getLogger("server-manager.runtime.lifecycle")


async def check_inner_process_running(
    docker: DockerRuntime, process_name: str
) -> Dict[str, Any]:
    container_id = await docker.get_container_id(process_name)
    if not container_id:
        return {"status": "Container Not Running", "container_running": False}

    state = await docker.inspect_state(container_id)
    if state != "running":
        return {"status": "Container Not Running", "container_running": False}

    main_command = await docker.inspect_main_command(container_id)
    if not main_command:
        return {"status": "Running", "container_running": True, "process_running": True}

    result = await docker.exec_in_container(container_id, "ps aux", timeout=15)
    if not result.success:
        return {
            "status": "Process Stopped",
            "container_running": True,
            "process_running": False,
        }

    process_name_mappings = {
        "apache2-foreground": ["apache2", "httpd"],
        "php-fpm": ["php-fpm"],
        "nginx": ["nginx"],
        "vite": ["node", "vite"],
        "npm": ["node", "npm"],
        "node": ["node"],
        "nodejs": ["node", "npm"],
        "minecraft": ["java"],
        "java": ["java"],
        "python": ["python", "python3"],
        "python3": ["python3"],
    }

    command_parts = main_command.split()
    search_terms: list[str] = []
    for part in command_parts:
        if part in process_name_mappings:
            search_terms.extend(process_name_mappings[part])
        elif len(part) > 2:
            search_terms.append(part)
    if not search_terms:
        search_terms = [p for p in command_parts if len(p) > 2]

    process_running = False
    for line in result.stdout.split("\n")[1:]:
        if not line.strip() or "ps aux" in line or "grep" in line:
            continue
        if "<defunct>" in line or " Z " in line:
            continue
        if any(term in line for term in search_terms):
            process_running = True
            break

    if process_running:
        return {"status": "Running", "container_running": True, "process_running": True}
    return {"status": "Process Stopped", "container_running": True, "process_running": False}


async def start_inner_process(docker: DockerRuntime, process_name: str) -> Dict[str, Any]:
    process_dir = docker.process_dir(process_name)
    container_id = await docker.get_container_id(process_name)

    if not container_id:
        up = await docker.compose_up(process_name)
        if not up.success:
            return {"success": False, "error": up.stderr or "Failed to start container"}
        await asyncio.sleep(2)
        container_id = await docker.get_container_id(process_name)

    if not container_id:
        return {"success": False, "error": "Container not found after compose up"}

    main_command = await docker.inspect_main_command(container_id)
    if not main_command:
        return {"success": False, "error": "No MAIN_COMMAND found in container environment"}

    await stop_inner_process(docker, process_name)

    log_file = f"/tmp/{process_name}_process.log"
    await docker.ensure_process_log_file(container_id, log_file)
    await docker.exec_in_container(container_id, f": > {shlex.quote(log_file)}")

    wrapper_script = textwrap.dedent(
        f"""#!/bin/bash
cd /app
exec {main_command} 2>&1 | tee -a {log_file}
"""
    )

    script_creation = f"""cat > /tmp/start_process.sh << 'EOF'
{wrapper_script}
EOF
chmod +x /tmp/start_process.sh"""

    script_result = await docker.exec_in_container(container_id, script_creation, timeout=30)
    if not script_result.success:
        return {"success": False, "error": f"Failed to create wrapper script: {script_result.stderr}"}

    start_result = await docker.run(
        ["docker", "exec", "-d", container_id, "/tmp/start_process.sh"],
        timeout=30,
    )
    if not start_result.success:
        return {"success": False, "error": start_result.stderr or "Failed to start process"}

    await asyncio.sleep(2)
    status = await check_inner_process_running(docker, process_name)
    if status.get("process_running"):
        return {"success": True, "message": "Process started successfully"}
    return {
        "success": False,
        "error": "Process started but crashed immediately. Check logs for details.",
    }


async def stop_inner_process(docker: DockerRuntime, process_name: str) -> Dict[str, Any]:
    container_id = await docker.get_container_id(process_name)
    if not container_id:
        return {"success": True, "message": "Container not running"}

    main_command = await docker.inspect_main_command(container_id)
    if not main_command:
        return {"success": False, "error": "No MAIN_COMMAND found in container environment"}

    command_parts = main_command.split()
    result = await docker.exec_in_container(container_id, "ps aux", timeout=15)
    if not result.success:
        return {"success": False, "error": "Failed to get process list"}

    killed = 0
    for line in result.stdout.split("\n")[1:]:
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        pid = parts[1]
        if any(part in line for part in command_parts if len(part) > 2):
            if "<defunct>" not in line and " Z " not in line:
                kill_res = await docker.run(
                    ["docker", "exec", container_id, "kill", "-TERM", pid],
                    timeout=10,
                )
                if kill_res.success:
                    killed += 1

    if killed:
        await asyncio.sleep(1)
        status = await check_inner_process_running(docker, process_name)
        if status.get("process_running"):
            return {
                "success": False,
                "error": "Process did not stop cleanly. Try again or check logs.",
            }
        return {"success": True, "message": f"Stopped {killed} process(es)"}

    status = await check_inner_process_running(docker, process_name)
    if not status.get("process_running"):
        return {"success": True, "message": "Process is already stopped"}
    return {"success": True, "message": "No matching processes found to stop"}


async def execute_command(
    docker: DockerRuntime,
    process_name: str,
    command: str,
    working_dir: str = "/app",
    timeout: int = 30,
    process_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a one-shot side command in the container (Azure App Service style).

    Does not send input to MAIN_COMMAND stdin. Requires the container to be
    running; the inner app may be stopped. Minecraft remains a special-case
    stdin forwarder; Node/Python/etc. use docker exec in working_dir.
    """
    container_id = await docker.get_container_id(process_name)
    if not container_id:
        return {"success": False, "error": "Container is not running"}

    state = await docker.inspect_state(container_id)
    if state != "running":
        return {"success": False, "error": "Container is not in running state"}

    if process_type == "minecraft":
        return await _minecraft_command(docker, container_id, process_name, command, timeout)

    log_file = f"/tmp/{process_name}_process.log"
    full_command = (
        f"cd {working_dir} && "
        f"echo \"[$(date -u +'%Y-%m-%d %H:%M:%S')] $ {command}\" >> {log_file} && "
        f"{command} 2>&1 | while IFS= read -r line; do "
        f"echo \"[$(date -u +'%Y-%m-%d %H:%M:%S')] $line\" >> {log_file}; "
        f"done"
    )
    result = await docker.exec_in_container(container_id, full_command, timeout=timeout)
    if result.success:
        return {
            "success": True,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode,
        }
    return {
        "success": False,
        "error": f"Command failed with return code {result.returncode}",
        "stdout": result.stdout,
        "stderr": result.stderr,
        "return_code": result.returncode,
    }


async def _minecraft_command(
    docker: DockerRuntime,
    container_id: str,
    process_name: str,
    command: str,
    timeout: int,
) -> Dict[str, Any]:
    sanitized = command.rstrip("\n") + "\n"
    encoded = base64.b64encode(sanitized.encode("utf-8")).decode("ascii")
    shell_script = textwrap.dedent(
        f"""
        MC_PID=$(ps -eo pid,command | grep -E 'fabric-server-launch.jar|minecraft_server.jar|server.jar' | grep -v grep | head -n 1 | awk '{{print $1}}')
        if [ -z "$MC_PID" ]; then
            MC_PID=$(pgrep -af 'java' | head -n 1 | awk '{{print $1}}')
        fi
        if [ -z "$MC_PID" ]; then
            echo "Minecraft JVM process not found" >&2
            exit 44
        fi
        echo '{encoded}' | base64 -d | tee /proc/$MC_PID/fd/0 > /dev/null
        """
    )
    result = await docker.exec_in_container(
        container_id, shell_script, timeout=timeout
    )
    if result.success:
        return {
            "success": True,
            "stdout": "Command forwarded to Minecraft server console",
            "stderr": "",
            "return_code": 0,
        }
    return {
        "success": False,
        "error": result.stderr.strip() or "Failed to forward command to Minecraft server",
        "stdout": result.stdout,
        "stderr": result.stderr,
        "return_code": result.returncode,
    }


async def execute_interactive(
    docker: DockerRuntime,
    process_name: str,
    command: str,
    working_dir: str = "/app",
) -> Dict[str, Any]:
    container_id = await docker.get_container_id(process_name)
    if not container_id:
        return {"success": False, "error": "Container is not running", "process": None}

    state = await docker.inspect_state(container_id)
    if state != "running":
        return {
            "success": False,
            "error": "Container is not in running state",
            "process": None,
        }

    full_command = f"cd {working_dir} && {command}"

    def _start():
        import subprocess

        proc = subprocess.Popen(
            ["docker", "exec", "-it", container_id, "sh", "-c", full_command],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        return proc

    proc = _start()
    return {
        "success": True,
        "process": proc,
        "message": "Interactive command started successfully",
    }
