from __future__ import annotations

import time

from openbridge.state.base import StateStore, StoredResponse


class MemoryStateStore(StateStore):
    def __init__(self) -> None:
        self._entries: dict[str, tuple[float, StoredResponse]] = {}

    async def get(self, response_id: str) -> StoredResponse | None:
        entry = self._entries.get(response_id)
        if not entry:
            return None
        expires_at, record = entry
        if expires_at and time.time() > expires_at:
            self._entries.pop(response_id, None)
            return None
        return record

    async def set(
        self, response_id: str, record: StoredResponse, ttl_seconds: int
    ) -> None:
        expires_at = time.time() + ttl_seconds if ttl_seconds > 0 else 0.0
        self._entries[response_id] = (expires_at, record)

    async def delete(self, response_id: str) -> None:
        self._entries.pop(response_id, None)

    async def close(self) -> None:
        return None
