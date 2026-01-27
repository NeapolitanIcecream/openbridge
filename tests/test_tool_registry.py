from openbridge.models.responses import ResponsesTool
from openbridge.tools.registry import ToolRegistry


def test_virtualize_builtin_tool():
    registry = ToolRegistry.default_registry()
    tools = [ResponsesTool(type="apply_patch")]
    result = registry.virtualize_tools(tools)

    assert len(result.chat_tools) == 1
    func_name = result.chat_tools[0].function.name
    assert result.function_name_map[func_name] == "apply_patch"
