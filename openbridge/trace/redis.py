from __future__ import annotations

import redis.asyncio as redis

from openbridge.trace.base import TraceRecord, TraceStore


class RedisTraceStore(TraceStore):
    def __init__(self, redis_url: str, *, key_prefix: str = "openbridge:trace") -> None:
        self._client = redis.from_url(redis_url, decode_responses=True)
        self._prefix = key_prefix.rstrip(":")

    def _req_key(self, request_id: str) -> str:
        return f"{self._prefix}:req:{request_id}"

    def _resp_key(self, response_id: str) -> str:
        return f"{self._prefix}:resp:{response_id}"

    async def get_by_request_id(self, request_id: str) -> TraceRecord | None:
        raw = await self._client.get(self._req_key(request_id))
        if not raw:
            return None
        return TraceRecord.model_validate_json(raw)

    async def get_by_response_id(self, response_id: str) -> TraceRecord | None:
        request_id = await self._client.get(self._resp_key(response_id))
        if not request_id:
            return None
        return await self.get_by_request_id(request_id)

    async def set(self, record: TraceRecord, ttl_seconds: int) -> None:
        req_key = self._req_key(record.request_id)
        value = record.model_dump_json()
        if ttl_seconds > 0:
            await self._client.setex(req_key, ttl_seconds, value)
        else:
            await self._client.set(req_key, value)

        if record.response_id:
            resp_key = self._resp_key(record.response_id)
            if ttl_seconds > 0:
                await self._client.setex(resp_key, ttl_seconds, record.request_id)
            else:
                await self._client.set(resp_key, record.request_id)

    async def close(self) -> None:
        await self._client.aclose()
