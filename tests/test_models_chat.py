from openbridge.models.chat import (
    ChatMessage,
    ChatToolCall,
    ChatToolCallFunction,
    ChatToolDefinition,
    ChatToolFunction,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChoice,
)


def test_chat_message_user():
    """Test creating a user message."""
    message = ChatMessage(role="user", content="Hello")

    assert message.role == "user"
    assert message.content == "Hello"
    assert message.tool_calls is None
    assert message.tool_call_id is None


def test_chat_message_assistant_with_content():
    """Test creating an assistant message with text content."""
    message = ChatMessage(role="assistant", content="Hi there!")

    assert message.role == "assistant"
    assert message.content == "Hi there!"


def test_chat_message_assistant_with_tool_calls():
    """Test creating an assistant message with tool calls."""
    tool_call = ChatToolCall(
        id="call_1",
        type="function",
        function=ChatToolCallFunction(name="get_weather", arguments='{"city":"NYC"}'),
    )
    message = ChatMessage(role="assistant", tool_calls=[tool_call])

    assert message.role == "assistant"
    assert message.tool_calls is not None
    assert len(message.tool_calls) == 1
    assert message.tool_calls[0].id == "call_1"


def test_chat_message_tool():
    """Test creating a tool message."""
    message = ChatMessage(
        role="tool", content='{"temp":25}', tool_call_id="call_1", name="get_weather"
    )

    assert message.role == "tool"
    assert message.content == '{"temp":25}'
    assert message.tool_call_id == "call_1"
    assert message.name == "get_weather"


def test_chat_message_system():
    """Test creating a system message."""
    message = ChatMessage(role="system", content="You are a helpful assistant.")

    assert message.role == "system"
    assert message.content == "You are a helpful assistant."


def test_chat_tool_function():
    """Test creating a ChatToolFunction."""
    func = ChatToolFunction(
        name="get_weather",
        description="Get current weather",
        parameters={"type": "object", "properties": {"city": {"type": "string"}}},
    )

    assert func.name == "get_weather"
    assert func.description == "Get current weather"
    assert func.parameters is not None


def test_chat_tool_definition():
    """Test creating a ChatToolDefinition."""
    func = ChatToolFunction(name="test_func")
    tool = ChatToolDefinition(type="function", function=func)

    assert tool.type == "function"
    assert tool.function.name == "test_func"


def test_chat_tool_call():
    """Test creating a ChatToolCall."""
    tool_call = ChatToolCall(
        id="call_123",
        type="function",
        function=ChatToolCallFunction(name="my_func", arguments='{"x":1}'),
    )

    assert tool_call.id == "call_123"
    assert tool_call.type == "function"
    assert tool_call.function.name == "my_func"
    assert tool_call.function.arguments == '{"x":1}'


def test_chat_completion_request_minimal():
    """Test creating a minimal ChatCompletionRequest."""
    request = ChatCompletionRequest(
        model="openai/gpt-4", messages=[ChatMessage(role="user", content="Hello")]
    )

    assert request.model == "openai/gpt-4"
    assert len(request.messages) == 1
    assert request.messages[0].content == "Hello"
    assert request.tools is None
    assert request.stream is None


def test_chat_completion_request_with_tools():
    """Test creating a ChatCompletionRequest with tools."""
    tool = ChatToolDefinition(
        type="function", function=ChatToolFunction(name="test_tool")
    )
    request = ChatCompletionRequest(
        model="openai/gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
        tools=[tool],
    )

    assert request.tools is not None
    assert len(request.tools) == 1
    assert request.tools[0].function.name == "test_tool"


def test_chat_completion_request_with_params():
    """Test creating a ChatCompletionRequest with various parameters."""
    request = ChatCompletionRequest(
        model="openai/gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
        temperature=0.7,
        max_tokens=100,
        top_p=0.9,
        stream=True,
    )

    assert request.temperature == 0.7
    assert request.max_tokens == 100
    assert request.top_p == 0.9
    assert request.stream is True


def test_chat_completion_response_minimal():
    """Test creating a minimal ChatCompletionResponse."""
    response = ChatCompletionResponse(choices=[])

    assert response.choices == []
    assert response.id is None
    assert response.usage is None


def test_chat_completion_response_with_message():
    """Test creating a ChatCompletionResponse with a message."""
    choice = ChatCompletionChoice(
        index=0,
        message=ChatMessage(role="assistant", content="Hello!"),
        finish_reason="stop",
    )
    response = ChatCompletionResponse(
        id="chat_123",
        object="chat.completion",
        created=1234567890,
        model="openai/gpt-4",
        choices=[choice],
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )

    assert response.id == "chat_123"
    assert response.model == "openai/gpt-4"
    assert len(response.choices) == 1
    assert response.choices[0].message is not None
    assert response.choices[0].message.content == "Hello!"
    assert response.usage is not None
    assert response.usage["total_tokens"] == 15


def test_chat_completion_choice_with_delta():
    """Test creating a ChatCompletionChoice with delta for streaming."""
    choice = ChatCompletionChoice(index=0, delta={"content": "Hello"})

    assert choice.index == 0
    assert choice.delta is not None
    assert choice.delta["content"] == "Hello"
    assert choice.message is None


def test_chat_message_extra_fields_allowed():
    """Test that ChatMessage allows extra fields via ConfigDict."""
    # This should not raise an error
    message = ChatMessage.model_validate(
        {"role": "user", "content": "Hi", "custom_field": "custom_value"}
    )

    assert message.role == "user"
    assert message.content == "Hi"


def test_chat_completion_request_extra_fields_allowed():
    """Test that ChatCompletionRequest allows extra fields."""
    request = ChatCompletionRequest.model_validate(
        {
            "model": "test/model",
            "messages": [{"role": "user", "content": "Hi"}],
            "custom_param": "custom_value",
        }
    )

    assert request.model == "test/model"
