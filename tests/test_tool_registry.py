import pytest

from openbridge.models.responses import ResponsesTool
from openbridge.tools.registry import ToolRegistry


def test_virtualize_builtin_tool():
    registry = ToolRegistry.default_registry()
    tools = [ResponsesTool(type="apply_patch")]
    result = registry.virtualize_tools(tools)

    assert len(result.chat_tools) == 1
    func_name = result.chat_tools[0].function.name
    assert result.function_name_map[func_name] == "apply_patch"


def test_duplicate_function_tool_names_raises():
    registry = ToolRegistry.default_registry()
    tools = [
        ResponsesTool(type="function", name="get_weather"),
        ResponsesTool(type="function", name="get_weather"),
    ]
    with pytest.raises(ValueError, match="Duplicate tool name"):
        registry.virtualize_tools(tools)


def test_tool_name_collision_between_function_and_builtin_raises():
    registry = ToolRegistry.default_registry()
    tools = [
        ResponsesTool(type="function", name="apply_patch"),
        ResponsesTool(type="apply_patch"),
    ]
    with pytest.raises(ValueError, match="Tool name collision"):
        registry.virtualize_tools(tools)
