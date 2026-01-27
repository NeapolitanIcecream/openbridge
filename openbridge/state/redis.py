from __future__ import annotations

import redis.asyncio as redis

from openbridge.state.base import StateStore, StoredResponse


class RedisStateStore(StateStore):
    def __init__(self, redis_url: str) -> None:
        self._client = redis.from_url(redis_url, decode_responses=True)

    async def get(self, response_id: str) -> StoredResponse | None:
        raw = await self._client.get(response_id)
        if not raw:
            return None
        return StoredResponse.model_validate_json(raw)

    async def set(self, response_id: str, record: StoredResponse, ttl_seconds: int) -> None:
        if ttl_seconds > 0:
            await self._client.setex(response_id, ttl_seconds, record.model_dump_json())
        else:
            await self._client.set(response_id, record.model_dump_json())

    async def delete(self, response_id: str) -> None:
        await self._client.delete(response_id)

    async def close(self) -> None:
        await self._client.aclose()
