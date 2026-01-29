from __future__ import annotations

import redis.asyncio as redis

from openbridge.state.base import StateStore, StoredResponse


class RedisStateStore(StateStore):
    def __init__(self, redis_url: str, *, key_prefix: str = "openbridge:state") -> None:
        self._client = redis.from_url(redis_url, decode_responses=True)
        self._prefix = (key_prefix or "").rstrip(":")

    def _key(self, response_id: str) -> str:
        if not self._prefix:
            return response_id
        return f"{self._prefix}:{response_id}"

    async def get(self, response_id: str) -> StoredResponse | None:
        raw = await self._client.get(self._key(response_id))
        if not raw and self._prefix:
            # Fallback: also check the raw response_id key when the prefixed key is missing.
            raw = await self._client.get(response_id)
        if not raw:
            return None
        return StoredResponse.model_validate_json(raw)

    async def set(
        self, response_id: str, record: StoredResponse, ttl_seconds: int
    ) -> None:
        key = self._key(response_id)
        if ttl_seconds > 0:
            await self._client.setex(key, ttl_seconds, record.model_dump_json())
        else:
            await self._client.set(key, record.model_dump_json())

    async def delete(self, response_id: str) -> None:
        keys = {self._key(response_id)}
        if self._prefix:
            keys.add(response_id)
        await self._client.delete(*keys)

    async def close(self) -> None:
        await self._client.aclose()
