import json

from openbridge.models.responses import InputItem
from openbridge.models.responses import ResponsesCreateRequest
from openbridge.tools.registry import ToolRegistry
from openbridge.translate.request import input_items_to_messages
from openbridge.translate.request import translate_request


def test_input_items_to_messages_tool_calls():
    registry = ToolRegistry.default_registry()
    items = [
        InputItem(role="user", content="hello"),
        InputItem(
            type="function_call",
            call_id="call_1",
            name="get_weather",
            arguments='{"city":"Paris"}',
        ),
        InputItem(type="function_call_output", call_id="call_1", output={"temp": 25}),
    ]

    messages = input_items_to_messages(items, tool_registry=registry)

    assert messages[0].role == "user"
    assert messages[1].role == "assistant"
    tool_calls = messages[1].tool_calls
    assert tool_calls is not None
    assert tool_calls[0].id == "call_1"
    assert tool_calls[0].function.name == "get_weather"
    assert messages[2].role == "tool"
    assert messages[2].tool_call_id == "call_1"
    tool_content = messages[2].content
    assert isinstance(tool_content, str)
    assert json.loads(tool_content)["temp"] == 25


def test_translate_request_adds_max_tokens_buffer():
    registry = ToolRegistry.default_registry()
    req = ResponsesCreateRequest.model_validate(
        {
            "model": "gpt-5.2-codex",
            "instructions": "Reply with exactly 'OK' and nothing else.",
            "input": "ping",
            "max_output_tokens": 16,
            "stream": False,
            "store": True,
        }
    )
    from openbridge.config import Settings

    settings = Settings(OPENROUTER_API_KEY="test", OPENBRIDGE_MAX_TOKENS_BUFFER="64")
    tr = translate_request(settings, req, registry, history_messages=[])
    assert tr.chat_request.max_tokens == 80

