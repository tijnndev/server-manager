"""Transport layer: SSE today, WebSocket-ready tomorrow."""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from typing import Generator, Iterable, Optional, Set, Type

from runtime.event_bus import SyncEventQueue
from runtime.events import (
    CONSOLE_EVENT_TYPES,
    BuildOutputEvent,
    ConsoleOutputEvent,
)


def format_timestamp(log_line: str) -> str:
    if not log_line.strip():
        return log_line

    match = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z) (.*)", log_line)
    if match:
        try:
            raw_timestamp = match.group(1)[:26]
            timestamp = datetime.strptime(raw_timestamp, "%Y-%m-%dT%H:%M:%S.%f")
            timestamp += timedelta(hours=2)
            return f"[{timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {match.group(2)}"
        except ValueError:
            pass
    return log_line


def ansi_to_html(ansi_code: str) -> str:
    color_map = {
        "31": "red",
        "32": "green",
        "33": "yellow",
        "34": "blue",
        "35": "magenta",
        "36": "cyan",
        "37": "white",
        "0": "white",
        "38;5;214": "orange",
        "38;5;226": "yellow",
        "38;5;196": "red",
    }
    return color_map.get(ansi_code, "white")


def colorize_log(log: str) -> str:
    ansi_escape = re.compile(r"\033\[(\d+(;\d+)*)m")
    return ansi_escape.sub(
        lambda match: f'<span style="color: {ansi_to_html(match.group(1))};">',
        log,
    ).replace("\033[0m", "</span>")


def format_console_event(event: ConsoleOutputEvent | BuildOutputEvent) -> str:
    line = event.line if isinstance(event, ConsoleOutputEvent) else event.line
    if getattr(event, "source", "") == "backlog":
        return colorize_log(format_timestamp(line))
    if isinstance(event, BuildOutputEvent):
        return colorize_log(format_timestamp(line))
    return colorize_log(format_timestamp(line) if "T" in line[:30] else line)


def format_backlog_line(line: str) -> str:
    return colorize_log(format_timestamp(line))


def backlog_lines_to_sse(lines: Iterable[str]) -> Generator[str, None, None]:
    """Yield SSE frames for historical log lines."""
    for line in lines:
        if line.strip():
            yield f"data: {format_backlog_line(line)}\n\n"


def sse_generator(
    queue: SyncEventQueue,
    event_types: Optional[Set[Type]] = None,
    heartbeat_interval: float = 15.0,
) -> Generator[str, None, None]:
    """Yield SSE frames from a sync event queue (no Docker calls)."""
    types = event_types or set(CONSOLE_EVENT_TYPES)
    last_heartbeat = time.time()

    while True:
        try:
            event = queue.get(timeout=0.5)
        except Exception:
            event = None

        if event is not None:
            if isinstance(event, (ConsoleOutputEvent, BuildOutputEvent)):
                formatted = format_console_event(event)
                yield f"data: {formatted}\n\n"
            continue

        now = time.time()
        if now - last_heartbeat >= heartbeat_interval:
            yield ": keepalive\n\n"
            last_heartbeat = now


def events_to_sse_lines(events: Iterable) -> Generator[str, None, None]:
    """Convert an iterable of console/build events to SSE payloads."""
    for event in events:
        if isinstance(event, (ConsoleOutputEvent, BuildOutputEvent)):
            yield f"data: {format_console_event(event)}\n\n"
