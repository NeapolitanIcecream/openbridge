#!/usr/bin/env python3
"""
Probe how OpenRouter Chat Completions returns tool_calls for various "tools".

This script intentionally does NOT execute any tool. It only forces the model to
emit a tool call so you can inspect the raw response JSON (and SSE chunks).

Usage:
  export OPENROUTER_API_KEY="..."
  uv run python docs/openrouter_apply_patch_probe.py --stream
  uv run python docs/openrouter_apply_patch_probe.py --tool shell
  uv run python docs/openrouter_apply_patch_probe.py --tool web_search --stream
  uv run python docs/openrouter_apply_patch_probe.py --tool web_search --builtin-tools
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx


OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"


DEFAULT_MODEL = "openai/gpt-5.2-codex"
DEFAULT_TIMEOUT_S = 120.0

DEFAULT_TOOL = "apply_patch"

DEFAULT_PATCH = """*** Begin Patch
*** Add File: probe.txt
+hello from apply_patch probe
*** End Patch
"""

DEFAULT_SHELL_COMMAND = "echo 'hello from shell probe'"
DEFAULT_WEB_QUERY = "What is the Cursor ApplyPatch format?"
DEFAULT_FILE_QUERY = "probe.txt"
DEFAULT_CODE = "print('hello from code_interpreter probe')"


def _pretty(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False)


def _tool_description(tool_name: str) -> str:
    return {
        "apply_patch": "Return a Cursor ApplyPatch patch as a string.",
        "shell": "Return a shell command to run locally (NOT executed here).",
        "local_shell": "Return a shell command to run locally (NOT executed here).",
        "web_search": "Return a web search request payload (NOT executed here).",
        "file_search": "Return a file search request payload (NOT executed here).",
        "computer_use_preview": "Return a computer-use action payload (NOT executed here).",
        "code_interpreter": "Return code to execute in a sandbox (NOT executed here).",
    }.get(tool_name, "Return a JSON payload for a tool call (NOT executed here).")


def _default_parameters_schema(tool_name: str) -> dict[str, Any]:
    # These schemas are intentionally simple. The goal is to observe tool_calls
    # shape and streaming delta behavior, not to faithfully implement OpenAI tools.
    if tool_name == "apply_patch":
        return {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "description": "The entire contents of the apply_patch command.",
                }
            },
            "required": ["input"],
            "additionalProperties": False,
        }

    if tool_name in ("shell", "local_shell"):
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout_ms": {"type": "integer", "minimum": 0},
                "cwd": {"type": "string"},
            },
            "required": ["command"],
            "additionalProperties": False,
        }

    if tool_name == "web_search":
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    if tool_name == "file_search":
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "glob": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    if tool_name == "computer_use_preview":
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["click", "type", "scroll", "screenshot", "noop"],
                },
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "text": {"type": "string"},
                "selector": {"type": "string"},
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    if tool_name == "code_interpreter":
        return {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "language": {
                    "type": "string",
                    "enum": ["python", "bash", "javascript"],
                },
            },
            "required": ["code"],
            "additionalProperties": False,
        }

    # Generic fallback: still lets you probe arbitrary tool names quickly.
    return {
        "type": "object",
        "properties": {"payload": {"type": "string"}},
        "required": ["payload"],
        "additionalProperties": False,
    }


def _default_args(tool_name: str, *, patch_text: str) -> dict[str, Any]:
    if tool_name == "apply_patch":
        return {"input": patch_text}
    if tool_name in ("shell", "local_shell"):
        return {"command": DEFAULT_SHELL_COMMAND, "timeout_ms": 10_000}
    if tool_name == "web_search":
        return {"query": DEFAULT_WEB_QUERY, "max_results": 3}
    if tool_name == "file_search":
        return {"query": DEFAULT_FILE_QUERY, "glob": "**/*", "max_results": 5}
    if tool_name == "computer_use_preview":
        return {"action": "screenshot"}
    if tool_name == "code_interpreter":
        return {"code": DEFAULT_CODE, "language": "python"}
    return {"payload": "probe"}


def _build_user_prompt(*, tool_name: str, args_obj: dict[str, Any]) -> str:
    if tool_name == "apply_patch":
        patch_input = args_obj.get("input")
        if not isinstance(patch_input, str) or not patch_input.strip():
            raise SystemExit(
                "apply_patch requires args.input to be a non-empty string"
            )
        return (
            "Call the tool `apply_patch` with exactly one argument object.\n"
            "The argument object MUST have exactly one key: `input`.\n"
            "Set `input` to EXACTLY the following string (including newlines), "
            "without adding any extra characters:\n"
            "<PATCH>\n"
            f"{patch_input}"
            "</PATCH>\n"
            "Do not wrap the patch in markdown fences."
        )

    args_json = _pretty(args_obj)
    return (
        f"Call the tool `{tool_name}` with exactly one argument object.\n"
        "The argument object MUST match the following JSON object (no extra keys):\n"
        "<ARGS_JSON>\n"
        f"{args_json}\n"
        "</ARGS_JSON>\n"
        "Do not wrap the JSON in markdown fences."
    )


def _build_payload(
    *,
    model: str,
    stream: bool,
    builtin_tools: bool,
    max_tokens: int,
    tool_name: str,
    tool_choice_mode: str,
    parameters_schema: dict[str, Any],
    args_obj: dict[str, Any],
) -> dict[str, Any]:
    system = (
        "You are a tool-calling assistant. "
        "You MUST call the tool exactly once, and you MUST NOT output normal text."
    )
    user = _build_user_prompt(tool_name=tool_name, args_obj=args_obj)

    if builtin_tools:
        # Experimental: try sending OpenAI Responses-style built-in tools to OpenRouter Chat Completions.
        # Most providers will reject this; the goal is to observe the error / behavior.
        tools: list[dict[str, Any]] = [{"type": tool_name}]
        tool_choice: Any
        if tool_choice_mode in ("force", "required"):
            tool_choice = "required"
        else:
            tool_choice = tool_choice_mode
    else:
        # OpenAI-compatible function tool (recommended "virtualization" approach).
        tools = [
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": _tool_description(tool_name),
                    "parameters": parameters_schema,
                },
            }
        ]
        if tool_choice_mode == "force":
            tool_choice = {"type": "function", "function": {"name": tool_name}}
        else:
            tool_choice = tool_choice_mode

    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "tools": tools,
        "tool_choice": tool_choice,
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": stream,
    }


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing env var: {name}")
    return value


def _extract_tool_calls_from_non_stream(resp_json: dict[str, Any]) -> Any:
    # OpenAI-compatible response shape:
    # choices[0].message.tool_calls = [{id,type,function:{name,arguments}}]
    try:
        return resp_json["choices"][0]["message"].get("tool_calls")
    except Exception:
        return None


def _best_effort_reconstruct_stream_tool_calls(
    events: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """
    Reconstruct tool_calls by concatenating streamed `function.arguments` deltas.
    Returns a mapping: tool_call_index -> {id,type,function:{name,arguments}}.
    """
    out: dict[int, dict[str, Any]] = {}
    for ev in events:
        choices = ev.get("choices") or []
        if not choices:
            continue
        delta = (choices[0] or {}).get("delta") or {}
        tool_calls = delta.get("tool_calls") or []
        for tc in tool_calls:
            idx = tc.get("index")
            if idx is None:
                # Some providers omit it; fall back to 0.
                idx = 0

            cur = out.setdefault(
                int(idx),
                {"id": "", "type": "", "function": {"name": "", "arguments": ""}},
            )
            if "id" in tc and tc["id"]:
                cur["id"] = tc["id"]
            if "type" in tc and tc["type"]:
                cur["type"] = tc["type"]
            fn = tc.get("function") or {}
            if "name" in fn and fn["name"]:
                cur["function"]["name"] = fn["name"]
            if "arguments" in fn and fn["arguments"]:
                cur["function"]["arguments"] += fn["arguments"]
    return out


def _print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def _post_non_stream(
    client: httpx.Client, headers: dict[str, str], payload: dict[str, Any]
) -> None:
    r = client.post(OPENROUTER_CHAT_COMPLETIONS_URL, headers=headers, json=payload)
    _print_header("HTTP")
    print(f"status: {r.status_code}")
    print(f"content-type: {r.headers.get('content-type')}")
    print(f"request-id: {r.headers.get('x-request-id')}")
    print("")
    print(r.text)
    r.raise_for_status()

    data = r.json()
    _print_header("Parsed JSON")
    print(_pretty(data))

    tool_calls = _extract_tool_calls_from_non_stream(data)
    _print_header("choices[0].message.tool_calls")
    print(_pretty(tool_calls))

    # Try to parse arguments JSON (it is often a JSON string).
    if tool_calls and isinstance(tool_calls, list):
        try:
            args_str = tool_calls[0]["function"]["arguments"]
            args = json.loads(args_str)
            _print_header("Parsed tool_calls[0].function.arguments (json.loads)")
            print(_pretty(args))
        except Exception as e:
            _print_header("Note")
            print(f"Could not json.loads(arguments): {e!r}")


def _post_stream(
    client: httpx.Client, headers: dict[str, str], payload: dict[str, Any]
) -> None:
    events: list[dict[str, Any]] = []

    with client.stream(
        "POST", OPENROUTER_CHAT_COMPLETIONS_URL, headers=headers, json=payload
    ) as r:
        _print_header("HTTP")
        print(f"status: {r.status_code}")
        print(f"content-type: {r.headers.get('content-type')}")
        print(f"request-id: {r.headers.get('x-request-id')}")
        r.raise_for_status()

        _print_header("SSE data lines (raw)")
        for line in r.iter_lines():
            if not line:
                continue
            if not line.startswith("data:"):
                # keep any non-standard lines for debugging
                print(line)
                continue

            data_str = line[len("data:") :].strip()
            if data_str == "[DONE]":
                print("data: [DONE]")
                break

            print(line)
            try:
                obj = json.loads(data_str)
                events.append(obj)
            except json.JSONDecodeError:
                # Keep going; sometimes providers send partial lines (rare).
                continue

    _print_header("Reconstructed tool_calls (best-effort from deltas)")
    reconstructed = _best_effort_reconstruct_stream_tool_calls(events)
    print(_pretty(reconstructed))

    # Convenience: show the patch if we can parse arguments JSON.
    if reconstructed:
        first = reconstructed.get(0) or next(iter(reconstructed.values()))
        try:
            args = json.loads(first["function"]["arguments"])
            patch = args.get("input")
            if isinstance(patch, str):
                _print_header("Extracted patch (args.input)")
                print(patch)
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Probe OpenRouter Chat Completions tool_calls shape (apply_patch by default)."
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter model id")
    parser.add_argument(
        "--tool",
        default=DEFAULT_TOOL,
        help=(
            "Tool name to probe. In function mode, this is the function tool name; "
            "in --builtin-tools mode, this is the built-in tool type."
        ),
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Use stream=true and print SSE data lines",
    )
    parser.add_argument(
        "--builtin-tools",
        action="store_true",
        help='Send tools=[{"type":"<tool>"}] (likely to error on Chat Completions); default uses function tool.',
    )
    parser.add_argument(
        "--tool-choice",
        default="force",
        choices=["force", "auto", "required", "none"],
        help=(
            'Tool choice behavior. "force" means tool_choice={"type":"function","function":{"name":...}} '
            "(only valid for function tools)."
        ),
    )
    parser.add_argument(
        "--args-json",
        default=None,
        help='Override tool arguments as a JSON object string (e.g. \'{"command":"echo hi"}\')',
    )
    parser.add_argument(
        "--schema-json",
        default=None,
        help="Override function tool parameters schema as a JSON object string (JSON Schema).",
    )
    parser.add_argument(
        "--patch-file",
        default=None,
        help="For --tool apply_patch: read patch content from a file instead of the built-in default.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=400,
        help="max_tokens to request",
    )
    parser.add_argument(
        "--print-request",
        action="store_true",
        help="Print the request payload JSON",
    )
    args = parser.parse_args()

    api_key = _require_env("OPENROUTER_API_KEY")

    patch_text = DEFAULT_PATCH
    if args.patch_file:
        patch_text = Path(args.patch_file).read_text(encoding="utf-8")

    tool_name = str(args.tool)
    parameters_schema = _default_parameters_schema(tool_name)
    if args.schema_json:
        try:
            parameters_schema = json.loads(args.schema_json)
        except json.JSONDecodeError as e:
            raise SystemExit(
                f"Invalid --schema-json (expected JSON object): {e}"
            ) from e

    args_obj = _default_args(tool_name, patch_text=patch_text)
    if args.args_json:
        try:
            args_obj = json.loads(args.args_json)
        except json.JSONDecodeError as e:
            raise SystemExit(f"Invalid --args-json (expected JSON object): {e}") from e

    payload = _build_payload(
        model=args.model,
        stream=args.stream,
        builtin_tools=args.builtin_tools,
        max_tokens=args.max_tokens,
        tool_name=tool_name,
        tool_choice_mode=args.tool_choice,
        parameters_schema=parameters_schema,
        args_obj=args_obj,
    )

    if args.print_request:
        _print_header("Request payload")
        print(_pretty(payload))

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # Optional attribution headers (safe defaults)
        "HTTP-Referer": os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost"),
        "X-Title": os.getenv("OPENROUTER_X_TITLE", "openbridge apply_patch probe"),
    }

    timeout = httpx.Timeout(DEFAULT_TIMEOUT_S)
    with httpx.Client(timeout=timeout) as client:
        if args.stream:
            _post_stream(client, headers, payload)
        else:
            _post_non_stream(client, headers, payload)


if __name__ == "__main__":
    main()
