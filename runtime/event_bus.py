"""Asyncio-compatible publish/subscribe event bus."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable, DefaultDict, List, Optional, Set, Type

logger = logging.getLogger("server-manager.runtime.bus")

EventHandler = Callable[[Any], Awaitable[None]]


class EventBus:
    """Central event bus. Subsystems publish; others subscribe by event type and/or process."""

    def __init__(self) -> None:
        self._handlers: DefaultDict[Type[Any], List[EventHandler]] = defaultdict(list)
        self._global_handlers: List[EventHandler] = []
        self._lock = asyncio.Lock()

    async def subscribe(
        self,
        event_type: Type[Any],
        handler: EventHandler,
    ) -> None:
        async with self._lock:
            self._handlers[event_type].append(handler)

    async def subscribe_all(self, handler: EventHandler) -> None:
        async with self._lock:
            self._global_handlers.append(handler)

    async def unsubscribe(
        self,
        event_type: Type[Any],
        handler: EventHandler,
    ) -> None:
        async with self._lock:
            handlers = self._handlers.get(event_type, [])
            if handler in handlers:
                handlers.remove(handler)

    async def publish(self, event: Any) -> None:
        event_type = type(event)
        async with self._lock:
            handlers = list(self._handlers.get(event_type, [])) + list(self._global_handlers)

        for handler in handlers:
            try:
                await handler(event)
            except Exception as exc:
                logger.exception("Event handler failed for %s: %s", event_type.__name__, exc)

    def subscribe_sync_queue(
        self,
        process_name: str,
        event_types: Optional[Set[Type[Any]]] = None,
        maxsize: int = 0,
    ) -> "SyncEventQueue":
        """Bridge for Flask/gevent: returns a thread-safe queue fed by async handlers."""
        return SyncEventQueue(self, process_name, event_types, maxsize=maxsize)


class SyncEventQueue:
    """Thread-safe queue receiving events from the asyncio bus."""

    def __init__(
        self,
        bus: EventBus,
        process_name: str,
        event_types: Optional[Set[Type[Any]]],
        maxsize: int = 0,
    ) -> None:
        import queue

        self._bus = bus
        self._process_name = process_name
        self._event_types = event_types
        self._queue: queue.Queue = queue.Queue(maxsize=maxsize)
        self._handler: Optional[EventHandler] = None
        self._registered = False

    async def _on_event(self, event: Any) -> None:
        if getattr(event, "process_name", None) != self._process_name:
            return
        if self._event_types is not None and type(event) not in self._event_types:
            return
        self._queue.put_nowait(event)

    async def register(self) -> None:
        if self._registered:
            return
        self._handler = self._on_event
        await self._bus.subscribe_all(self._handler)
        self._registered = True

    async def unregister(self) -> None:
        if self._handler and self._registered:
            await self._bus.unsubscribe_all(self._handler)
            self._registered = False

    def get(self, timeout: Optional[float] = None) -> Any:
        if timeout is None:
            return self._queue.get()
        return self._queue.get(timeout=timeout)

    def put_nowait(self, event: Any) -> None:
        self._queue.put_nowait(event)


# Patch unsubscribe_all onto EventBus
async def _unsubscribe_all(self: EventBus, handler: EventHandler) -> None:
    async with self._lock:
        if handler in self._global_handlers:
            self._global_handlers.remove(handler)
        for handlers in self._handlers.values():
            if handler in handlers:
                handlers.remove(handler)


EventBus.unsubscribe_all = _unsubscribe_all  # type: ignore[method-assign]
