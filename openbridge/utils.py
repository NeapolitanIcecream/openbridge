from __future__ import annotations

import time
import uuid
from typing import Any

import orjson


def now_ts() -> int:
    return int(time.time())


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def json_dumps(data: Any) -> str:
    return orjson.dumps(data).decode("utf-8")


def drop_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}
