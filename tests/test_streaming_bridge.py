import json

from openbridge.streaming.bridge import ResponsesStreamTranslator
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
