from __future__ import annotations

from openbridge.models.chat import ChatToolDefinition, ChatToolFunction


def apply_patch_tool() -> ChatToolDefinition:
    return ChatToolDefinition(
        type="function",
        function=ChatToolFunction(
            name="ob_apply_patch",
            description="Return a Cursor ApplyPatch patch as a string.",
            parameters={
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "string",
                        "description": "Cursor ApplyPatch patch string.",
                    }
                },
                "required": ["patch"],
                "additionalProperties": False,
            },
        ),
    )


def shell_tool() -> ChatToolDefinition:
    return ChatToolDefinition(
        type="function",
        function=ChatToolFunction(
            name="ob_shell",
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
    }
