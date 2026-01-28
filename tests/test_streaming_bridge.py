import json
from contextlib import asynccontextmanager

import pytest

from openbridge.config import Settings
from openbridge.models.chat import ChatCompletionRequest, ChatMessage
from openbridge.streaming.bridge import ResponsesStreamTranslator
from openbridge.streaming.bridge import stream_responses_events
from openbridge.tools.registry import ToolVirtualizationResult


def test_streaming_text_events():
    tool_map = ToolVirtualizationResult(chat_tools=[], function_name_map={}, external_name_map={})
    translator = ResponsesStreamTranslator(
        response_id="resp_1",
        model="openai/gpt-4.1",
        created_at=1,
        tool_map=tool_map,
    )

    events = []
    events += translator.start_events()
    events += translator.process_chunk({"choices": [{"delta": {"content": "Hello "}}]})
    events += translator.process_chunk({"choices": [{"delta": {"content": "world"}}]})
    events += translator.finish_events()

    done_events = [event for event in events if event["event"] == "response.output_text.done"]
    assert done_events
    data = json.loads(done_events[0]["data"])
    assert data["text"] == "Hello world"


def test_streaming_tool_call_events():
    tool_map = ToolVirtualizationResult(
        chat_tools=[],
        function_name_map={"ob_apply_patch": "apply_patch"},
        external_name_map={"apply_patch": "ob_apply_patch"},
    )
    translator = ResponsesStreamTranslator(
        response_id="resp_2",
        model="openai/gpt-4.1",
        created_at=1,
        tool_map=tool_map,
    )

    events = []
    events += translator.start_events()
    events += translator.process_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "ob_apply_patch",
                                    "arguments": "{\"patch\":\"x\"}",
                                },
                            }
                        ]
                    }
                }
            ]
        }
    )
    events += translator.finish_events()

    delta_events = [
        event for event in events if event["event"] == "response.function_call_arguments.delta"
    ]
    assert delta_events
    delta_payload = json.loads(delta_events[0]["data"])
    assert delta_payload["delta"] == "{\"patch\":\"x\"}"


def test_streaming_tool_call_id_late():
    tool_map = ToolVirtualizationResult(
        chat_tools=[],
        function_name_map={"ob_apply_patch": "apply_patch"},
        external_name_map={"apply_patch": "ob_apply_patch"},
    )
    translator = ResponsesStreamTranslator(
        response_id="resp_3",
        model="openai/gpt-4.1",
        created_at=1,
        tool_map=tool_map,
    )

    events = []
    events += translator.start_events()

    # First chunk: name and arguments arrive without id.
    events += translator.process_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "type": "function",
                                "function": {
                                    "name": "ob_apply_patch",
                                    "arguments": "{\"patch\":\"x\"}",
                                },
                            }
                        ]
                    }
                }
            ]
        }
    )
    assert not [e for e in events if e["event"] == "response.output_item.added"]

    # Second chunk: id arrives later.
    events += translator.process_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {},
                            }
                        ]
                    }
                }
            ]
        }
    )

    added_events = [event for event in events if event["event"] == "response.output_item.added"]
    assert added_events
    added_payload = json.loads(added_events[0]["data"])
    assert added_payload["item"]["call_id"] == "call_1"

    delta_events = [
        event for event in events if event["event"] == "response.function_call_arguments.delta"
    ]
    assert delta_events
    delta_payload = json.loads(delta_events[0]["data"])
    assert delta_payload["delta"] == "{\"patch\":\"x\"}"


@pytest.mark.asyncio
async def test_stream_responses_events_early_failure_emits_failed():
    class FailingClient:
        @asynccontextmanager
        async def connect_chat_completions_sse(self, payload):  # noqa: ANN001
            raise RuntimeError("boom")
            yield  # pragma: no cover

    settings = Settings(
        OPENROUTER_API_KEY="test",
        OPENBRIDGE_RETRY_MAX_ATTEMPTS=1,
        OPENBRIDGE_RETRY_BACKOFF=0.0,
        OPENBRIDGE_RETRY_MAX_SECONDS=0.0,
    )
    tool_map = ToolVirtualizationResult(chat_tools=[], function_name_map={}, external_name_map={})
    chat_request = ChatCompletionRequest(
        model="openai/gpt-4.1",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )

    events = []
    async for event in stream_responses_events(
        client=FailingClient(),
        chat_request=chat_request,
        tool_map=tool_map,
        response_id="resp_fail",
        created_at=1,
        settings=settings,
        on_complete=None,
    ):
        events.append(event)

    assert events[0]["event"] == "response.created"
    assert events[-1]["event"] == "response.failed"
