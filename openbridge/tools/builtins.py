from __future__ import annotations

from openbridge.models.chat import ChatToolDefinition, ChatToolFunction


def apply_patch_tool() -> ChatToolDefinition:
    return ChatToolDefinition(
        type="function",
        function=ChatToolFunction(
            name="apply_patch",
            description=(
                "Use the `apply_patch` tool to edit files. "
                "Return the entire apply_patch patch as a string in `input`."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "The entire contents of the apply_patch command.",
                    }
                },
                "required": ["input"],
                "additionalProperties": False,
            },
        ),
    )


def shell_tool() -> ChatToolDefinition:
    return ChatToolDefinition(
        type="function",
        function=ChatToolFunction(
            name="shell",
            description="Return a shell command to run locally.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_ms": {"type": "integer", "minimum": 0},
                    "cwd": {"type": "string"},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        ),
    )


def local_shell_tool() -> ChatToolDefinition:
    return ChatToolDefinition(
        type="function",
        function=ChatToolFunction(
            name="local_shell",
            description="Return a shell command to run locally.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_ms": {"type": "integer", "minimum": 0},
                    "cwd": {"type": "string"},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        ),
    )


def default_builtin_tools() -> dict[str, ChatToolDefinition]:
    return {
        "apply_patch": apply_patch_tool(),
        "shell": shell_tool(),
        "local_shell": local_shell_tool(),
    }
