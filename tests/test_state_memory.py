import asyncio

import pytest

from openbridge.models.chat import ChatMessage
from openbridge.models.responses import ResponsesCreateResponse, ResponseOutputItem
from openbridge.state.base import StoredResponse
from openbridge.state.memory import MemoryStateStore


@pytest.mark.asyncio
async def test_memory_store_set_and_get():
    """Test setting and getting a response from memory store."""
    store = MemoryStateStore()
    response = ResponsesCreateResponse(
        id="resp_1",
        created_at=1234567890,
        model="test/model",
        output=[
            ResponseOutputItem(
                id="item_1", type="message", role="assistant", content=[]
            )
        ],
    )
    stored = StoredResponse(
        response=response,
        messages=[ChatMessage(role="user", content="hello")],
        tool_function_map={},
        model="test/model",
    )

    await store.set("resp_1", stored, ttl_seconds=3600)
    retrieved = await store.get("resp_1")

    assert retrieved is not None
    assert retrieved.response.id == "resp_1"
    assert retrieved.model == "test/model"
    assert len(retrieved.messages) == 1


@pytest.mark.asyncio
async def test_memory_store_get_nonexistent():
    """Test getting a nonexistent response returns None."""
    store = MemoryStateStore()
    result = await store.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_memory_store_delete():
    """Test deleting a response from memory store."""
    store = MemoryStateStore()
    response = ResponsesCreateResponse(
        id="resp_2", created_at=1, model="test/model", output=[]
    )
    stored = StoredResponse(
        response=response, messages=[], tool_function_map={}, model="test/model"
    )

    await store.set("resp_2", stored, ttl_seconds=3600)
    await store.delete("resp_2")
    retrieved = await store.get("resp_2")

    assert retrieved is None


@pytest.mark.asyncio
async def test_memory_store_ttl_expiration():
    """Test that entries expire after TTL."""
    store = MemoryStateStore()
    response = ResponsesCreateResponse(
        id="resp_3", created_at=1, model="test/model", output=[]
    )
    stored = StoredResponse(
        response=response, messages=[], tool_function_map={}, model="test/model"
    )

    # Set with 1 second TTL
    await store.set("resp_3", stored, ttl_seconds=1)

    # Should exist immediately
    result = await store.get("resp_3")
    assert result is not None

    # Wait for expiration
    await asyncio.sleep(1.1)

    # Should be gone after expiration
    result = await store.get("resp_3")
    assert result is None


@pytest.mark.asyncio
async def test_memory_store_ttl_zero_no_expiration():
    """Test that TTL of 0 means no expiration."""
    store = MemoryStateStore()
    response = ResponsesCreateResponse(
        id="resp_4", created_at=1, model="test/model", output=[]
    )
    stored = StoredResponse(
        response=response, messages=[], tool_function_map={}, model="test/model"
    )

    # Set with 0 TTL (no expiration)
    await store.set("resp_4", stored, ttl_seconds=0)

    # Should still exist
    result = await store.get("resp_4")
    assert result is not None


@pytest.mark.asyncio
async def test_memory_store_delete_nonexistent():
    """Test deleting a nonexistent entry doesn't raise error."""
    store = MemoryStateStore()
    # Should not raise an exception
    await store.delete("nonexistent")


@pytest.mark.asyncio
async def test_memory_store_overwrite():
    """Test overwriting an existing entry."""
    store = MemoryStateStore()
    response1 = ResponsesCreateResponse(
        id="resp_5", created_at=1, model="model1", output=[]
    )
    stored1 = StoredResponse(
        response=response1, messages=[], tool_function_map={}, model="model1"
    )

    response2 = ResponsesCreateResponse(
        id="resp_5", created_at=2, model="model2", output=[]
    )
    stored2 = StoredResponse(
        response=response2, messages=[], tool_function_map={}, model="model2"
    )

    await store.set("resp_5", stored1, ttl_seconds=3600)
    await store.set("resp_5", stored2, ttl_seconds=3600)

    retrieved = await store.get("resp_5")
    assert retrieved is not None
    assert retrieved.model == "model2"
    assert retrieved.response.created_at == 2
