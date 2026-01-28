from openbridge.models.responses import (
    InputItem,
    ResponseOutputItem,
    ResponseOutputText,
    ResponsesCreateRequest,
    ResponsesCreateResponse,
    ResponsesTool,
    ResponsesToolFunction,
    ResponseTextConfig,
    ResponseTextFormat,
    ToolChoiceFunction,
    ToolChoiceAllowedTools,
)


def test_input_item_user_message():
    """Test creating a user message InputItem."""
    item = InputItem(role="user", content="Hello")

    assert item.role == "user"
    assert item.content == "Hello"
    assert item.type is None


def test_input_item_function_call():
    """Test creating a function call InputItem."""
    item = InputItem(
        type="function_call",
        call_id="call_1",
        name="get_weather",
        arguments='{"city":"Paris"}',
    )

    assert item.type == "function_call"
    assert item.call_id == "call_1"
    assert item.name == "get_weather"
    assert item.arguments == '{"city":"Paris"}'


def test_input_item_function_call_output():
    """Test creating a function call output InputItem."""
    item = InputItem(type="function_call_output", call_id="call_1", output={"temp": 25})

    assert item.type == "function_call_output"
    assert item.call_id == "call_1"
    assert item.output == {"temp": 25}


def test_responses_tool_with_function():
    """Test creating a ResponsesTool with function type."""
    tool = ResponsesTool(
        type="function",
        function=ResponsesToolFunction(
            name="get_weather",
            description="Get weather data",
            parameters={"type": "object"},
        ),
    )

    assert tool.type == "function"
    assert tool.function is not None
    assert tool.function.name == "get_weather"
    assert tool.function.description == "Get weather data"


def test_responses_tool_builtin():
    """Test creating a ResponsesTool for builtin type."""
    tool = ResponsesTool(
        type="apply_patch", name="apply_patch", description="Apply a patch"
    )

    assert tool.type == "apply_patch"
    assert tool.name == "apply_patch"
    assert tool.function is None


def test_tool_choice_function():
    """Test creating a ToolChoiceFunction."""
    choice = ToolChoiceFunction(type="function", name="specific_tool")

    assert choice.type == "function"
    assert choice.name == "specific_tool"


def test_tool_choice_allowed_tools():
    """Test creating a ToolChoiceAllowedTools."""
    tool = ResponsesTool(type="function", name="tool1")
    choice = ToolChoiceAllowedTools(type="allowed_tools", mode="auto", tools=[tool])

    assert choice.type == "allowed_tools"
    assert choice.mode == "auto"
    assert len(choice.tools) == 1


def test_response_text_format_json_schema():
    """Test creating a ResponseTextFormat with json_schema."""
    format_config = ResponseTextFormat.model_validate(
        {
            "type": "json_schema",
            "name": "MySchema",
            "strict": True,
            "schema": {"type": "object", "properties": {}},
        }
    )

    assert format_config.type == "json_schema"
    assert format_config.name == "MySchema"
    assert format_config.strict is True
    assert format_config.schema_ is not None


def test_response_text_config():
    """Test creating a ResponseTextConfig."""
    format_config = ResponseTextFormat.model_validate({"type": "json_object"})
    text_config = ResponseTextConfig(format=format_config)

    assert text_config.format is not None
    assert text_config.format.type == "json_object"


def test_responses_create_request_minimal():
    """Test creating a minimal ResponsesCreateRequest."""
    request = ResponsesCreateRequest(model="openai/gpt-4", input="Hello")

    assert request.model == "openai/gpt-4"
    assert request.input == "Hello"
    assert request.stream is False
    assert request.tools is None


def test_responses_create_request_with_input_items():
    """Test creating a ResponsesCreateRequest with input items."""
    items = [InputItem(role="user", content="Hello")]
    request = ResponsesCreateRequest(model="openai/gpt-4", input=items)

    assert isinstance(request.input, list)
    assert len(request.input) == 1
    assert request.input[0].content == "Hello"


def test_responses_create_request_with_tools():
    """Test creating a ResponsesCreateRequest with tools."""
    tool = ResponsesTool(
        type="function",
        function=ResponsesToolFunction(name="get_weather"),
    )
    request = ResponsesCreateRequest(
        model="openai/gpt-4", input="Hello", tools=[tool], tool_choice="auto"
    )

    assert request.tools is not None
    assert len(request.tools) == 1
    assert request.tool_choice == "auto"


def test_responses_create_request_with_all_params():
    """Test creating a ResponsesCreateRequest with all parameters."""
    request = ResponsesCreateRequest(
        model="openai/gpt-4",
        input="Hello",
        instructions="Be helpful",
        max_output_tokens=100,
        temperature=0.7,
        top_p=0.9,
        verbosity="normal",
        stream=True,
        previous_response_id="resp_123",
        store=True,
        metadata={"user_id": "123"},
    )

    assert request.instructions == "Be helpful"
    assert request.max_output_tokens == 100
    assert request.temperature == 0.7
    assert request.top_p == 0.9
    assert request.verbosity == "normal"
    assert request.stream is True
    assert request.previous_response_id == "resp_123"
    assert request.store is True
    assert request.metadata is not None
    assert request.metadata["user_id"] == "123"


def test_response_output_text():
    """Test creating a ResponseOutputText."""
    output = ResponseOutputText(text="Hello, world!")

    assert output.type == "output_text"
    assert output.text == "Hello, world!"


def test_response_output_item_message():
    """Test creating a message ResponseOutputItem."""
    text = ResponseOutputText(text="Hello")
    item = ResponseOutputItem(
        id="item_1", type="message", role="assistant", content=[text]
    )

    assert item.id == "item_1"
    assert item.type == "message"
    assert item.role == "assistant"
    assert item.content is not None
    assert len(item.content) == 1
    assert item.content[0].text == "Hello"


def test_response_output_item_function_call():
    """Test creating a function_call ResponseOutputItem."""
    item = ResponseOutputItem(
        id="item_2",
        type="function_call",
        call_id="call_1",
        name="get_weather",
        arguments='{"city":"NYC"}',
    )

    assert item.id == "item_2"
    assert item.type == "function_call"
    assert item.call_id == "call_1"
    assert item.name == "get_weather"
    assert item.arguments == '{"city":"NYC"}'


def test_responses_create_response():
    """Test creating a ResponsesCreateResponse."""
    output_item = ResponseOutputItem(
        id="item_1",
        type="message",
        role="assistant",
        content=[ResponseOutputText(text="Hi")],
    )
    response = ResponsesCreateResponse(
        id="resp_1",
        created_at=1234567890,
        model="openai/gpt-4",
        output=[output_item],
        usage={"total_tokens": 10},
        metadata={"key": "value"},
    )

    assert response.id == "resp_1"
    assert response.object == "response"
    assert response.created_at == 1234567890
    assert response.model == "openai/gpt-4"
    assert len(response.output) == 1
    assert response.usage is not None
    assert response.usage["total_tokens"] == 10
    assert response.metadata is not None
    assert response.metadata["key"] == "value"


def test_responses_create_response_empty_output():
    """Test creating a ResponsesCreateResponse with empty output."""
    response = ResponsesCreateResponse(
        id="resp_2", created_at=1, model="test/model", output=[]
    )

    assert response.id == "resp_2"
    assert len(response.output) == 0
    assert response.object == "response"


def test_responses_tool_extra_fields_allowed():
    """Test that ResponsesTool allows extra fields."""
    tool = ResponsesTool.model_validate(
        {"type": "custom", "custom_field": "custom_value"}
    )

    assert tool.type == "custom"


def test_input_item_extra_fields_allowed():
    """Test that InputItem allows extra fields."""
    item = InputItem.model_validate(
        {"role": "user", "content": "Hi", "custom_field": "value"}
    )

    assert item.role == "user"
    assert item.content == "Hi"
