from openbridge.tools.builtins import (
    apply_patch_tool,
    default_builtin_tools,
    shell_tool,
)


def test_apply_patch_tool_structure():
    """Test that apply_patch_tool returns correct structure."""
    tool = apply_patch_tool()

    assert tool.type == "function"
    assert tool.function.name == "apply_patch"
    assert tool.function.description is not None
    assert "apply_patch" in tool.function.description
    assert tool.function.parameters is not None


def test_apply_patch_tool_parameters():
    """Test that apply_patch_tool has correct parameters."""
    tool = apply_patch_tool()
    params = tool.function.parameters
    assert params is not None

    assert params["type"] == "object"
    assert "input" in params["properties"]
    assert params["properties"]["input"]["type"] == "string"
    assert "required" in params
    assert "input" in params["required"]
    assert params["additionalProperties"] is False


def test_shell_tool_structure():
    """Test that shell_tool returns correct structure."""
    tool = shell_tool()

    assert tool.type == "function"
    assert tool.function.name == "shell"
    assert tool.function.description is not None
    assert "shell command" in tool.function.description
    assert tool.function.parameters is not None


def test_shell_tool_parameters():
    """Test that shell_tool has correct parameters."""
    tool = shell_tool()
    params = tool.function.parameters
    assert params is not None

    assert params["type"] == "object"
    assert "command" in params["properties"]
    assert params["properties"]["command"]["type"] == "string"
    assert "timeout_ms" in params["properties"]
    assert params["properties"]["timeout_ms"]["type"] == "integer"
    assert params["properties"]["timeout_ms"]["minimum"] == 0
    assert "cwd" in params["properties"]
    assert params["properties"]["cwd"]["type"] == "string"
    assert "required" in params
    assert "command" in params["required"]
    assert params["additionalProperties"] is False


def test_default_builtin_tools_contains_expected_tools():
    """Test that default_builtin_tools returns expected tools."""
    tools = default_builtin_tools()

    assert isinstance(tools, dict)
    assert "apply_patch" in tools
    assert "shell" in tools


def test_default_builtin_tools_tool_types():
    """Test that default_builtin_tools returns correct tool types."""
    tools = default_builtin_tools()

    apply_patch = tools["apply_patch"]
    shell = tools["shell"]

    assert apply_patch.type == "function"
    assert shell.type == "function"
    assert apply_patch.function.name == "apply_patch"
    assert shell.function.name == "shell"


def test_default_builtin_tools_keys_match_external_names():
    """Test that default_builtin_tools keys match external names (not internal names)."""
    tools = default_builtin_tools()

    # Keys should be external names
    assert "apply_patch" in tools
    assert "shell" in tools
    # Internal names should not be keys (defensive)
    assert "ob_apply_patch" not in tools
    assert "ob_shell" not in tools
