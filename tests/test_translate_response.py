from openbridge.models.chat import (
    ChatCompletionResponse,
    ChatMessage,
    ChatToolCall,
    ChatToolCallFunction,
    ChatCompletionChoice,
)
from openbridge.translate.response import chat_response_to_responses
from openbridge.tools.registry import ToolVirtualizationResult


def test_chat_response_with_text_only():
    """Test converting a chat response with only text content."""
    tool_map = ToolVirtualizationResult(
        chat_tools=[], function_name_map={}, external_name_map={}
    )
    chat_response = ChatCompletionResponse(
        id="chat_1",
        object="chat.completion",
        created=1234567890,
        model="openai/gpt-4.1",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatMessage(role="assistant", content="Hello, world!"),
                finish_reason="stop",
            )
        ],
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )

    responses = chat_response_to_responses(
        chat_response,
        model="openai/gpt-4.1",
        tool_map=tool_map,
        response_id="resp_test",
        created_at=9999,
    )

    assert responses.id == "resp_test"
    assert responses.created_at == 9999
    assert responses.model == "openai/gpt-4.1"
    assert len(responses.output) == 1
    assert responses.output[0].type == "message"
    assert responses.output[0].role == "assistant"
    assert responses.output[0].content is not None
    assert responses.output[0].content[0].text == "Hello, world!"
    assert responses.usage is not None
    assert responses.usage["prompt_tokens"] == 10


def test_chat_response_with_tool_calls():
    """Test converting a chat response with tool calls (unmapped function)."""
    tool_map = ToolVirtualizationResult(
        chat_tools=[],
        function_name_map={},
        external_name_map={},
    )
    chat_response = ChatCompletionResponse(
        id="chat_2",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatMessage(
                    role="assistant",
                    tool_calls=[
                        ChatToolCall(
                            id="call_1",
                            type="function",
                            function=ChatToolCallFunction(
                                name="get_weather", arguments='{"city":"Paris"}'
                            ),
                        )
                    ],
                ),
            )
        ],
    )

    responses = chat_response_to_responses(
        chat_response, model="openai/gpt-4.1", tool_map=tool_map
    )

    assert len(responses.output) == 1
    assert responses.output[0].type == "function_call"
    assert responses.output[0].call_id == "call_1"
    assert responses.output[0].name == "get_weather"
    assert responses.output[0].arguments == '{"city":"Paris"}'


def test_chat_response_with_builtin_tool():
    """Test converting a chat response with builtin tool (apply_patch)."""
    tool_map = ToolVirtualizationResult(
        chat_tools=[],
        function_name_map={"ob_apply_patch": "apply_patch"},
        external_name_map={"apply_patch": "ob_apply_patch"},
    )
    chat_response = ChatCompletionResponse(
        choices=[
            ChatCompletionChoice(
                message=ChatMessage(
                    role="assistant",
                    tool_calls=[
                        ChatToolCall(
                            id="call_2",
                            type="function",
                            function=ChatToolCallFunction(
                                name="ob_apply_patch", arguments='{"patch":"diff"}'
                            ),
                        )
                    ],
                )
            )
        ]
    )

    responses = chat_response_to_responses(
        chat_response, model="test/model", tool_map=tool_map
    )

    assert len(responses.output) == 1
    assert responses.output[0].type == "apply_patch_call"
    assert responses.output[0].name == "apply_patch"
    assert responses.output[0].call_id == "call_2"


def test_chat_response_with_text_and_tool_calls():
    """Test converting a chat response with both text and tool calls."""
    tool_map = ToolVirtualizationResult(
        chat_tools=[], function_name_map={}, external_name_map={}
    )
    chat_response = ChatCompletionResponse(
        choices=[
            ChatCompletionChoice(
                message=ChatMessage(
                    role="assistant",
                    content="Let me calculate that.",
                    tool_calls=[
                        ChatToolCall(
                            id="call_3",
                            type="function",
                            function=ChatToolCallFunction(
                                name="calc", arguments='{"x":2}'
                            ),
                        )
                    ],
                )
            )
        ]
    )

    responses = chat_response_to_responses(
        chat_response, model="test/model", tool_map=tool_map
    )

    # Tool calls come first, then text
    assert len(responses.output) == 2
    assert responses.output[0].type == "function_call"
    assert responses.output[1].type == "message"
    assert responses.output[1].content is not None
    assert responses.output[1].content[0].text == "Let me calculate that."


def test_chat_response_empty_choices():
    """Test converting a chat response with no choices."""
    tool_map = ToolVirtualizationResult(
        chat_tools=[], function_name_map={}, external_name_map={}
    )
    chat_response = ChatCompletionResponse(choices=[])

    responses = chat_response_to_responses(
        chat_response, model="test/model", tool_map=tool_map
    )

    assert len(responses.output) == 0


def test_chat_response_generates_ids_when_not_provided():
    """Test that response_id and created_at are generated if not provided."""
    tool_map = ToolVirtualizationResult(
        chat_tools=[], function_name_map={}, external_name_map={}
    )
    chat_response = ChatCompletionResponse(
        choices=[
            ChatCompletionChoice(message=ChatMessage(role="assistant", content="Hi"))
        ]
    )

    responses = chat_response_to_responses(
        chat_response, model="test/model", tool_map=tool_map
    )

    assert responses.id.startswith("resp_")
    assert responses.created_at > 0
