from __future__ import annotations

import time
from collections import OrderedDict

from openbridge.trace.base import TraceRecord, TraceStore


class MemoryTraceStore(TraceStore):
    def __init__(self, *, max_entries: int = 200) -> None:
        self._max_entries = max(1, int(max_entries))
        self._entries: "OrderedDict[str, tuple[float, TraceRecord]]" = OrderedDict()
        self._response_to_request: dict[str, str] = {}

    def _evict(self, request_id: str) -> None:
        entry = self._entries.pop(request_id, None)
        if not entry:
            return
        _, record = entry
        if record.response_id:
            self._response_to_request.pop(record.response_id, None)

    def _purge_expired(self) -> None:
        if not self._entries:
            return
        now = time.time()
        expired: list[str] = []
        for request_id, (expires_at, _) in self._entries.items():
            if expires_at and now > expires_at:
                expired.append(request_id)
        for request_id in expired:
            self._evict(request_id)

    async def get_by_request_id(self, request_id: str) -> TraceRecord | None:
        self._purge_expired()
        entry = self._entries.get(request_id)
        if not entry:
            return None
        expires_at, record = entry
        if expires_at and time.time() > expires_at:
            self._evict(request_id)
            return None
        # Keep LRU-ish ordering for hot entries.
        self._entries.move_to_end(request_id)
        return record

    async def get_by_response_id(self, response_id: str) -> TraceRecord | None:
        self._purge_expired()
        request_id = self._response_to_request.get(response_id)
        if not request_id:
            return None
        return await self.get_by_request_id(request_id)

    async def set(self, record: TraceRecord, ttl_seconds: int) -> None:
        self._purge_expired()
        request_id = record.request_id

        existing = self._entries.get(request_id)
        if existing:
            _, old_record = existing
            if old_record.response_id and old_record.response_id != record.response_id:
                self._response_to_request.pop(old_record.response_id, None)

        expires_at = time.time() + ttl_seconds if ttl_seconds > 0 else 0.0
        self._entries[request_id] = (expires_at, record)
        self._entries.move_to_end(request_id)

        if record.response_id:
            self._response_to_request[record.response_id] = request_id

        while len(self._entries) > self._max_entries:
            oldest_request_id, (_, oldest_record) = self._entries.popitem(last=False)
            if oldest_record.response_id:
                self._response_to_request.pop(oldest_record.response_id, None)

    async def close(self) -> None:
        return None
