from __future__ import annotations

import json
from dataclasses import dataclass

from openbridge.models.chat import ChatToolDefinition, ChatToolFunction
from openbridge.models.responses import InputItem, ResponsesTool
from openbridge.tools.builtins import default_builtin_tools
from openbridge.utils import json_dumps


@dataclass
class ToolVirtualizationResult:
    chat_tools: list[ChatToolDefinition]
    function_name_map: dict[str, str]
    external_name_map: dict[str, str]


class ToolRegistry:
    def __init__(self, prefix: str = "ob_") -> None:
        self._prefix = prefix
        self._builtins: dict[str, ChatToolDefinition] = default_builtin_tools()

    @classmethod
    def default_registry(cls) -> "ToolRegistry":
        return cls()

    def register_builtin(self, external_type: str, tool_def: ChatToolDefinition) -> None:
        self._builtins[external_type] = tool_def

    def function_name_for_external(self, external_type: str) -> str:
        tool_def = self._builtins.get(external_type)
        if tool_def is not None:
            return tool_def.function.name
        return f"{self._prefix}{external_type}"

    def tool_definition_for_external(self, external_type: str) -> ChatToolDefinition:
        tool_def = self._builtins.get(external_type)
        if tool_def is not None:
            return tool_def
        return ChatToolDefinition(
            type="function",
            function=ChatToolFunction(
                name=self.function_name_for_external(external_type),
                description=f"Return a JSON payload for {external_type}.",
                parameters={
                    "type": "object",
                    "properties": {"payload": {"type": "string"}},
                    "required": ["payload"],
                    "additionalProperties": False,
                },
            ),
        )

    def virtualize_tools(
        self, tools: list[ResponsesTool] | None
    ) -> ToolVirtualizationResult:
        if not tools:
            return ToolVirtualizationResult([], {}, {})
        chat_tools: list[ChatToolDefinition] = []
        function_name_map: dict[str, str] = {}
        external_name_map: dict[str, str] = {}
        seen_names: set[str] = set()

        for tool in tools:
            if tool.type == "function":
                function = tool.function or ChatToolFunction(
                    name=tool.name or "",
                    description=tool.description,
                    parameters=tool.parameters,
                )
                if not function.name:
                    continue
                if function.name.startswith(self._prefix):
                    raise ValueError(
                        f"Function tool name must not start with reserved prefix {self._prefix!r}: {function.name!r}"
                    )
                if function.name in seen_names:
                    raise ValueError(f"Duplicate tool name: {function.name!r}")
                seen_names.add(function.name)
                chat_tools.append(
                    ChatToolDefinition(
                        type="function",
                        function=ChatToolFunction(
                            name=function.name,
                            description=function.description,
                            parameters=function.parameters,
                        ),
                    )
                )
            else:
                external_type = tool.type
                tool_def = self.tool_definition_for_external(external_type)
                name = tool_def.function.name
                if name in seen_names:
                    raise ValueError(
                        f"Tool name collision for external type {external_type!r}: {name!r}"
                    )
                seen_names.add(name)
                chat_tools.append(
                    ChatToolDefinition(
                        type="function",
                        function=ChatToolFunction(
                            name=name,
                            description=tool_def.function.description,
                            parameters=tool_def.function.parameters,
                        ),
                    )
                )
                function_name_map[name] = external_type
                external_name_map[external_type] = name

        return ToolVirtualizationResult(chat_tools, function_name_map, external_name_map)

    def tool_call_args_from_item(self, external_type: str, item: InputItem) -> str:
        data = item.model_dump(exclude_none=True, mode="python")
        data.pop("type", None)
        data.pop("id", None)
        data.pop("call_id", None)
        if "arguments" in data and isinstance(data["arguments"], str):
            try:
                json.loads(data["arguments"])
                return data["arguments"]
            except json.JSONDecodeError:
                pass
        return json_dumps(data)

    # Note: All virtualized tool names are deterministic and must be collision-free.
