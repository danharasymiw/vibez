import asyncio
from typing import Any, Callable, Coroutine


class TaskQueue:
    def __init__(self):
        self._lock = asyncio.Lock()
        self.pending = 0

    async def run(self, coro_func: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
        self.pending += 1
        try:
            async with self._lock:
                return await coro_func()
        finally:
            self.pending -= 1
