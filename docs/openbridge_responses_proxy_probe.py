#!/usr/bin/env python3
"""
Probe whether OpenBridge correctly:
1) Proxies OpenAI Responses API requests to OpenRouter Chat Completions upstream.
2) Handles OpenAI Responses built-in tool calls via tool virtualization (e.g. apply_patch).
3) Supports multi-turn conversations (stateless via explicit history items, and optionally stateful via previous_response_id).
4) Translates streaming SSE chunks into OpenAI Responses streaming events.
5) Supports structured outputs (json_schema) and state endpoints when enabled.

This script acts like a minimal Responses client and can run multiple scenarios.
Some scenarios require state storage to be enabled on the server (Memory/Redis).

Notes:
- OpenBridge must be running (default: http://127.0.0.1:8000).
- OpenBridge server must be configured with OPENROUTER_API_KEY so it can reach upstream.
- This script does NOT execute any tool; it only simulates tool output.
- If your client uses https:// against an HTTP OpenBridge server, the server will log
  `Invalid HTTP request received.` and the client will disconnect. Use an http:// base URL
  or enable TLS on OpenBridge.

Usage:
  uv run python docs/openbridge_responses_proxy_probe.py
  uv run python docs/openbridge_responses_proxy_probe.py --suite quick
  uv run python docs/openbridge_responses_proxy_probe.py --suite smoke
  uv run python docs/openbridge_responses_proxy_probe.py --suite full
  uv run python docs/openbridge_responses_proxy_probe.py --scenarios tool_loop_builtin multi_turn_stateless
  uv run python docs/openbridge_responses_proxy_probe.py --stream  # legacy: stream the first request of tool_loop_builtin
  uv run python docs/openbridge_responses_proxy_probe.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

import httpx
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_MODEL = "gpt-5.2-codex"
DEFAULT_TIMEOUT_S = 120.0
DEFAULT_TOOL = "apply_patch"

DEFAULT_SUITE = "smoke"

DEFAULT_PATCH = """*** Begin Patch
*** Add File: probe.txt
+hello from OpenBridge probe
*** End Patch
"""

DEFAULT_SHELL_COMMAND = "echo 'hello from OpenBridge probe'"
DEFAULT_NONCE_PREFIX = "nonce:"


console = Console()


def _setup_logging(level: str) -> None:
    logger.remove()

    def _sink(message: object) -> None:
        record = message.record  # type: ignore[attr-defined]
        timestamp = record["time"].strftime("%Y-%m-%d %H:%M:%S")
        level_name = record["level"].name
        text = Text(f"{timestamp} | {level_name:<8} | {record['message']}")
        if record["exception"]:
            text.append(f"\n{record['exception']}")
        console.print(text)

    logger.add(_sink, level=level, backtrace=False, diagnose=False)


def _pretty(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False)


def _panel(title: str, body: str) -> Panel:
    return Panel.fit(body, title=title, border_style="cyan")


def _join_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def _headers(client_api_key: str | None) -> dict[str, str]:
    if not client_api_key:
        return {"content-type": "application/json"}
    return {"authorization": f"Bearer {client_api_key}", "content-type": "application/json"}


def _http_get(
    *,
    base_url: str,
    headers: dict[str, str],
    timeout_s: float,
    verify: bool,
    path: str,
) -> tuple[httpx.Response, dict[str, Any]]:
    url = _join_url(base_url, path)
    with httpx.Client(timeout=timeout_s, verify=verify) as client:
        r = client.get(url, headers=headers)
    try:
        data = r.json()
    except ValueError:
        data = {"_raw_text": r.text}
    return r, data


def _http_delete(
    *,
    base_url: str,
    headers: dict[str, str],
    timeout_s: float,
    verify: bool,
    path: str,
) -> tuple[httpx.Response, dict[str, Any]]:
    url = _join_url(base_url, path)
    with httpx.Client(timeout=timeout_s, verify=verify) as client:
        r = client.delete(url, headers=headers)
    try:
        data = r.json()
    except ValueError:
        data = {"_raw_text": r.text}
    return r, data


def _require_server_up(
    base_url: str, headers: dict[str, str], timeout_s: float, *, verify: bool
) -> None:
    url = _join_url(base_url, "/healthz")
    try:
        with httpx.Client(timeout=timeout_s, verify=verify) as client:
            r = client.get(url, headers=headers)
        if r.status_code != 200:
            raise RuntimeError(f"/healthz returned {r.status_code}: {r.text}")
    except Exception as exc:  # noqa: BLE001
        parsed = urlparse(base_url)
        if (
            parsed.scheme == "https"
            and parsed.hostname in ("127.0.0.1", "localhost")
            and parsed.port is not None
        ):
            http_base_url = base_url.replace("https://", "http://", 1)
            http_url = _join_url(http_base_url, "/healthz")
            try:
                with httpx.Client(timeout=timeout_s) as client:
                    r2 = client.get(http_url, headers=headers)
                if r2.status_code == 200:
                    raise SystemExit(
                        "OpenBridge is reachable via HTTP, but you are using an HTTPS base URL.\n\n"
                        f"Try:\n  --base-url {http_base_url}\n\n"
                        "Or enable TLS on OpenBridge by setting:\n"
                        "  OPENBRIDGE_SSL_CERTFILE\n"
                        "  OPENBRIDGE_SSL_KEYFILE\n"
                        "  OPENBRIDGE_SSL_KEYFILE_PASSWORD (optional)\n\n"
                        f"Root cause: {exc}"
                    ) from exc
            except Exception:  # noqa: BLE001
                # Ignore fallback failures; report the original error below.
                pass
        raise SystemExit(
            "OpenBridge is not reachable.\n\n"
            "Start the server in another terminal:\n"
            "  export OPENROUTER_API_KEY='...'\n"
            "  uv sync\n"
            "  uv run openbridge\n\n"
            f"Then retry. Root cause: {exc}"
        ) from exc


@dataclass(frozen=True)
class ToolCall:
    type: str
    call_id: str
    name: str | None
    arguments: str | None


def _extract_first_call_item(output_items: Iterable[dict[str, Any]]) -> ToolCall | None:
    for item in output_items:
        item_type = str(item.get("type") or "")
        call_id = str(item.get("call_id") or "")
        if item_type not in ("function_call",) and not item_type.endswith("_call"):
            continue
        if not call_id:
            continue
        return ToolCall(
            type=item_type,
            call_id=call_id,
            name=item.get("name"),
            arguments=item.get("arguments"),
        )
    return None


def _extract_assistant_text(output_items: Iterable[dict[str, Any]]) -> str | None:
    for item in output_items:
        if not isinstance(item, dict):
            continue
        if str(item.get("type")) != "message":
            continue
        if str(item.get("role") or "") != "assistant":
            continue
        content = item.get("content")
        if not isinstance(content, list) or not content:
            continue
        chunks: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if str(part.get("type")) != "output_text":
                continue
            text = part.get("text")
            if text is None:
                continue
            chunks.append(str(text))
        if chunks:
            return "".join(chunks)
    return None


def _extract_output_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    output = data.get("output")
    if not isinstance(output, list):
        raise AssertionError("Response JSON missing output[]")
    items: list[dict[str, Any]] = []
    for item in output:
        if isinstance(item, dict):
            items.append(item)
    return items


def _responses_create(
    *,
    base_url: str,
    headers: dict[str, str],
    timeout_s: float,
    verify: bool,
    payload: dict[str, Any],
) -> tuple[httpx.Response, dict[str, Any]]:
    url = _join_url(base_url, "/v1/responses")
    with httpx.Client(timeout=timeout_s, verify=verify) as client:
        r = client.post(url, headers=headers, json=payload)
    try:
        data = r.json()
    except ValueError:
        data = {"_raw_text": r.text}
    return r, data


def _responses_create_stream(
    *,
    base_url: str,
    headers: dict[str, str],
    timeout_s: float,
    verify: bool,
    payload: dict[str, Any],
) -> tuple[httpx.Response, list[dict[str, Any]]]:
    """
    Parse OpenBridge SSE output (EventSourceResponse).

    Each event usually looks like:
      event: response.created
      data: {"response":{...}}

    Returns a list of {"event": <name>, "data": <parsed json or raw string>}.
    """
    url = _join_url(base_url, "/v1/responses")
    events: list[dict[str, Any]] = []
    with httpx.Client(timeout=timeout_s, verify=verify) as client:
        with client.stream("POST", url, headers=headers, json=payload) as r:
            event_name: str | None = None
            data_lines: list[str] = []
            for line in r.iter_lines():
                if line is None:
                    continue
                if not line:
                    if event_name is not None:
                        raw = "\n".join(data_lines).strip()
                        parsed: Any = raw
                        if raw:
                            try:
                                parsed = json.loads(raw)
                            except json.JSONDecodeError:
                                parsed = raw
                        events.append({"event": event_name, "data": parsed})
                    event_name = None
                    data_lines = []
                    continue
                if line.startswith("event:"):
                    event_name = line[len("event:") :].strip()
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[len("data:") :].strip())
                    continue
            if event_name is not None:
                raw = "\n".join(data_lines).strip()
                parsed2: Any = raw
                if raw:
                    try:
                        parsed2 = json.loads(raw)
                    except json.JSONDecodeError:
                        parsed2 = raw
                events.append({"event": event_name, "data": parsed2})
    return r, events


def _build_tool_call_request_builtin(
    *,
    model: str,
    tool_type: str,
    patch: str,
    shell_command: str,
    stream: bool,
) -> dict[str, Any]:
    # Avoid referencing internal tool names. Force a call to the only available tool.
    instructions = (
        "You are a tool-calling assistant. "
        "You MUST call the only available tool exactly once and output no normal text."
    )
    if tool_type == "apply_patch":
        user = (
            "Call the only available tool with exactly one argument object.\n"
            "The argument object MUST have exactly one key: `input`.\n"
            "Set `input` to EXACTLY the following string (including newlines), without adding any extra characters:\n"
            "<PATCH>\n"
            f"{patch}"
            "</PATCH>\n"
            "Do not wrap the patch in markdown fences."
        )
    elif tool_type == "shell":
        args_obj = {"command": shell_command, "timeout_ms": 10_000}
        user = (
            "Call the only available tool with exactly one argument object.\n"
            "The argument object MUST match the following JSON object (no extra keys):\n"
            "<ARGS_JSON>\n"
            f"{_pretty(args_obj)}\n"
            "</ARGS_JSON>\n"
            "Do not wrap the JSON in markdown fences."
        )
    else:
        # Fallback schema used by OpenBridge for unknown built-in tools.
        args_obj = {"payload": "probe"}
        user = (
            "Call the only available tool with exactly one argument object.\n"
            "The argument object MUST match the following JSON object (no extra keys):\n"
            "<ARGS_JSON>\n"
            f"{_pretty(args_obj)}\n"
            "</ARGS_JSON>\n"
            "Do not wrap the JSON in markdown fences."
        )
    return {
        "model": model,
        "instructions": instructions,
        "input": user,
        "tools": [{"type": tool_type}],
        "tool_choice": "required",
        "temperature": 0,
        "max_output_tokens": 400,
        "stream": stream,
        "store": True,
    }


def _build_tool_output_request_builtin(
    *,
    model: str,
    tool_type: str,
    previous_response_id: str | None,
    stateless_with_tool_call_item: ToolCall | None,
    call_id: str,
    tool_output: Any,
    stream: bool,
) -> dict[str, Any]:
    instructions = "You are a helpful assistant. Confirm you received the tool result and summarize briefly."
    input_items: list[dict[str, Any]] = []
    if stateless_with_tool_call_item is not None:
        input_items.append(
            {
                "type": f"{tool_type}_call",
                "call_id": stateless_with_tool_call_item.call_id,
                "name": tool_type,
                "arguments": stateless_with_tool_call_item.arguments,
            }
        )
    input_items.extend(
        [
            {"type": f"{tool_type}_call_output", "call_id": call_id, "output": tool_output},
            {"role": "user", "content": "Continue with a normal assistant response."},
        ]
    )
    payload: dict[str, Any] = {
        "model": model,
        "instructions": instructions,
        "input": input_items,
        "tools": [{"type": tool_type}],
        "tool_choice": "none",
        "temperature": 0,
        "max_output_tokens": 200,
        "stream": stream,
        "store": True,
    }
    if previous_response_id:
        payload["previous_response_id"] = previous_response_id
    return payload


def _print_http_summary(title: str, r: httpx.Response) -> None:
    request_id = r.headers.get("x-request-id")
    content_type = r.headers.get("content-type")
    table = Table(title=title)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("status", str(r.status_code))
    table.add_row("content-type", str(content_type))
    if request_id:
        table.add_row("x-request-id", request_id)
    console.print(table)


def _print_response_json(title: str, data: dict[str, Any]) -> None:
    console.print(_panel(title, _pretty(data)))


class Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    status: Status
    detail: str


@dataclass
class RunContext:
    base_url: str
    headers: dict[str, str]
    timeout_s: float
    verify: bool
    model: str
    tool: str
    patch: str
    shell_command: str
    legacy_stream_tool_call: bool
    force_stateless: bool
    print_requests: bool
    shared: dict[str, Any]


ScenarioFn = Callable[[RunContext], ScenarioResult]


def _ok(name: str, detail: str = "") -> ScenarioResult:
    return ScenarioResult(name=name, status=Status.PASS, detail=detail or "ok")


def _warn(name: str, detail: str) -> ScenarioResult:
    return ScenarioResult(name=name, status=Status.WARN, detail=detail)


def _skip(name: str, detail: str) -> ScenarioResult:
    return ScenarioResult(name=name, status=Status.SKIP, detail=detail)


def _fail(name: str, detail: str) -> ScenarioResult:
    return ScenarioResult(name=name, status=Status.FAIL, detail=detail)


def _get_completed_response_from_events(
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    completed = next((e for e in events if e.get("event") == "response.completed"), None)
    if not completed or not isinstance(completed.get("data"), dict):
        raise AssertionError("Missing response.completed in SSE stream")
    response = completed["data"].get("response")
    if not isinstance(response, dict):
        raise AssertionError("Invalid response.completed payload: missing data.response")
    return response


def scenario_basic_text(ctx: RunContext) -> ScenarioResult:
    name = "basic_text"
    expected = "PONG_OB_PROBE"
    payload = {
        "model": ctx.model,
        "instructions": f"Reply with exactly {expected!r} and nothing else.",
        "input": "ping",
        "temperature": 0,
        "max_output_tokens": 32,
        "stream": False,
        "store": True,
    }
    if ctx.print_requests:
        _print_response_json(f"{name} request", payload)
    r, data = _responses_create(
        base_url=ctx.base_url,
        headers=ctx.headers,
        timeout_s=ctx.timeout_s,
        verify=ctx.verify,
        payload=payload,
    )
    _print_http_summary(f"{name} response", r)
    if r.status_code >= 400:
        _print_response_json(f"{name} response JSON", data)
        return _fail(name, f"HTTP {r.status_code}")
    if data.get("object") != "response":
        return _fail(name, "missing object=response")
    output_items = _extract_output_items(data)
    text = _extract_assistant_text(output_items)
    if (text or "").strip() != expected:
        _print_response_json(f"{name} response JSON", data)
        return _fail(name, f"unexpected assistant text: {(text or '').strip()!r}")
    ctx.shared["basic_response_id"] = data.get("id")
    return _ok(name, f"assistant_text={expected!r}")


def scenario_tool_loop_builtin(ctx: RunContext) -> ScenarioResult:
    name = "tool_loop_builtin"

    # 1) Force a built-in tool call.
    req1 = _build_tool_call_request_builtin(
        model=ctx.model,
        tool_type=ctx.tool,
        patch=ctx.patch,
        shell_command=ctx.shell_command,
        stream=ctx.legacy_stream_tool_call,
    )
    if ctx.print_requests:
        _print_response_json(f"{name} request #1 (force tool call)", req1)

    if ctx.legacy_stream_tool_call:
        r1, events1 = _responses_create_stream(
            base_url=ctx.base_url,
            headers=ctx.headers,
            timeout_s=ctx.timeout_s,
            verify=ctx.verify,
            payload=req1,
        )
        _print_http_summary(f"{name} response #1 (stream)", r1)
        if r1.status_code >= 400:
            console.print(_panel("Raw SSE (first 30 events)", _pretty(events1[:30])))
            return _fail(name, f"HTTP {r1.status_code} on request #1")
        console.print(_panel("SSE events (first 30)", _pretty(events1[:30])))
        data1 = _get_completed_response_from_events(events1)
    else:
        r1, data1 = _responses_create(
            base_url=ctx.base_url,
            headers=ctx.headers,
            timeout_s=ctx.timeout_s,
            verify=ctx.verify,
            payload=req1,
        )
        _print_http_summary(f"{name} response #1 (non-stream)", r1)
        if r1.status_code >= 400:
            _print_response_json(f"{name} response #1 JSON", data1)
            return _fail(name, f"HTTP {r1.status_code} on request #1")

    output1 = _extract_output_items(data1)
    tool_call = _extract_first_call_item(output1)
    if tool_call is None:
        _print_response_json(f"{name} response #1 JSON", data1)
        return _fail(name, "missing tool call item in response #1")
    if tool_call.type != f"{ctx.tool}_call":
        _print_response_json(f"{name} response #1 JSON", data1)
        return _fail(
            name, f"unexpected tool call item.type: {tool_call.type!r} (expected {ctx.tool}_call)"
        )

    tool_summary = Table(title=f"{name}: detected tool call (response #1)")
    tool_summary.add_column("field", style="bold")
    tool_summary.add_column("value")
    tool_summary.add_row("item.type", tool_call.type)
    tool_summary.add_row("call_id", tool_call.call_id)
    tool_summary.add_row("name", str(tool_call.name))
    console.print(tool_summary)

    if tool_call.arguments:
        try:
            parsed_args = json.loads(tool_call.arguments)
            console.print(_panel("Parsed tool arguments (json.loads)", _pretty(parsed_args)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to json.loads(tool_call.arguments): {}", exc)

    # 2) Simulate sending tool output back (built-in *_call_output), expect normal assistant output.
    tool_output = {
        "ok": True,
        "note": "Tool execution is simulated by the probe script.",
        "tool_type": ctx.tool,
    }

    previous_response_id: str | None = None
    stateless_tool_call_item: ToolCall | None = None
    if not ctx.force_stateless:
        previous_response_id = str(data1.get("id") or "")
        if not previous_response_id:
            previous_response_id = None
    if ctx.force_stateless or previous_response_id is None:
        stateless_tool_call_item = tool_call

    req2 = _build_tool_output_request_builtin(
        model=ctx.model,
        tool_type=ctx.tool,
        previous_response_id=previous_response_id,
        stateless_with_tool_call_item=stateless_tool_call_item,
        call_id=tool_call.call_id,
        tool_output=tool_output,
        stream=False,
    )
    if ctx.print_requests:
        _print_response_json(f"{name} request #2 (send tool output)", req2)

    r2, data2 = _responses_create(
        base_url=ctx.base_url,
        headers=ctx.headers,
        timeout_s=ctx.timeout_s,
        verify=ctx.verify,
        payload=req2,
    )
    _print_http_summary(f"{name} response #2 (non-stream)", r2)
    if r2.status_code >= 400:
        _print_response_json(f"{name} response #2 JSON", data2)
        if (
            not ctx.force_stateless
            and previous_response_id is not None
            and r2.status_code in (404, 501)
        ):
            logger.warning(
                "Stateful follow-up failed with status {}. Retrying stateless tool loop.",
                r2.status_code,
            )
            req2b = _build_tool_output_request_builtin(
                model=ctx.model,
                tool_type=ctx.tool,
                previous_response_id=None,
                stateless_with_tool_call_item=tool_call,
                call_id=tool_call.call_id,
                tool_output=tool_output,
                stream=False,
            )
            r2b, data2b = _responses_create(
                base_url=ctx.base_url,
                headers=ctx.headers,
                timeout_s=ctx.timeout_s,
                verify=ctx.verify,
                payload=req2b,
            )
            _print_http_summary(f"{name} response #2 (stateless retry)", r2b)
            if r2b.status_code >= 400:
                _print_response_json(f"{name} response #2b JSON", data2b)
                return _fail(name, f"tool loop follow-up failed: HTTP {r2b.status_code}")
            data2 = data2b
            output2 = _extract_output_items(data2)
            text = _extract_assistant_text(output2)
            if not text or not text.strip():
                _print_response_json(f"{name} response #2b JSON", data2)
                return _fail(name, "missing assistant message after tool output (stateless retry)")
            return _warn(name, "state store unavailable; tool loop verified stateless")
        return _fail(name, f"tool loop follow-up failed: HTTP {r2.status_code}")

    output2 = _extract_output_items(data2)
    text2 = _extract_assistant_text(output2)
    if not text2 or not text2.strip():
        _print_response_json(f"{name} response #2 JSON", data2)
        return _fail(name, "missing assistant message after tool output")
    return _ok(name, "built-in tool loop ok")


def scenario_multi_turn_stateless(ctx: RunContext) -> ScenarioResult:
    name = "multi_turn_stateless"
    nonce = secrets.token_hex(8)
    ctx.shared["nonce"] = nonce

    req1 = {
        "model": ctx.model,
        "instructions": (
            "When the user sends a message starting with 'nonce:', "
            "reply with exactly 'ACK' and nothing else."
        ),
        "input": f"{DEFAULT_NONCE_PREFIX} {nonce}",
        "temperature": 0,
        "max_output_tokens": 16,
        "stream": False,
        "store": True,
    }
    if ctx.print_requests:
        _print_response_json(f"{name} request #1", req1)
    r1, data1 = _responses_create(
        base_url=ctx.base_url,
        headers=ctx.headers,
        timeout_s=ctx.timeout_s,
        verify=ctx.verify,
        payload=req1,
    )
    _print_http_summary(f"{name} response #1", r1)
    if r1.status_code >= 400:
        _print_response_json(f"{name} response #1 JSON", data1)
        return _fail(name, f"HTTP {r1.status_code} on turn #1")

    out1 = _extract_output_items(data1)
    ack = (_extract_assistant_text(out1) or "").strip()
    if ack != "ACK":
        _print_response_json(f"{name} response #1 JSON", data1)
        return _fail(name, f"unexpected ACK: {ack!r}")

    ctx.shared["multi_turn_response_id"] = data1.get("id")

    req2 = {
        "model": ctx.model,
        "instructions": (
            "Return ONLY the nonce value you saw in the previous user message "
            "after 'nonce:'. Output the exact nonce string and nothing else."
        ),
        "input": [
            {"role": "user", "content": f"{DEFAULT_NONCE_PREFIX} {nonce}"},
            {"role": "assistant", "content": "ACK"},
            {"role": "user", "content": "What nonce did you see?"},
        ],
        "temperature": 0,
        "max_output_tokens": 32,
        "stream": False,
        "store": True,
    }
    if ctx.print_requests:
        _print_response_json(f"{name} request #2", req2)
    r2, data2 = _responses_create(
        base_url=ctx.base_url,
        headers=ctx.headers,
        timeout_s=ctx.timeout_s,
        verify=ctx.verify,
        payload=req2,
    )
    _print_http_summary(f"{name} response #2", r2)
    if r2.status_code >= 400:
        _print_response_json(f"{name} response #2 JSON", data2)
        return _fail(name, f"HTTP {r2.status_code} on turn #2")

    out2 = _extract_output_items(data2)
    text2 = (_extract_assistant_text(out2) or "").strip()
    if text2 != nonce:
        _print_response_json(f"{name} response #2 JSON", data2)
        return _fail(name, f"unexpected nonce: {text2!r} (expected {nonce!r})")
    return _ok(name, "stateless history items ok")


def scenario_multi_turn_stateful(ctx: RunContext) -> ScenarioResult:
    name = "multi_turn_stateful"
    response_id = ctx.shared.get("multi_turn_response_id")
    nonce = ctx.shared.get("nonce")
    if not isinstance(response_id, str) or not response_id:
        return _skip(name, "missing turn #1 response id; run multi_turn_stateless first")
    if not isinstance(nonce, str) or not nonce:
        return _skip(name, "missing nonce; run multi_turn_stateless first")

    req2 = {
        "model": ctx.model,
        "instructions": (
            "Return ONLY the nonce value you saw in the previous user message "
            "after 'nonce:'. Output the exact nonce string and nothing else."
        ),
        "input": "What nonce did you see?",
        "temperature": 0,
        "max_output_tokens": 32,
        "stream": False,
        "store": True,
        "previous_response_id": response_id,
    }
    if ctx.print_requests:
        _print_response_json(f"{name} request", req2)
    r2, data2 = _responses_create(
        base_url=ctx.base_url,
        headers=ctx.headers,
        timeout_s=ctx.timeout_s,
        verify=ctx.verify,
        payload=req2,
    )
    _print_http_summary(f"{name} response", r2)
    if r2.status_code in (404, 501):
        _print_response_json(f"{name} response JSON", data2)
        return _skip(name, f"state store unavailable (HTTP {r2.status_code})")
    if r2.status_code >= 400:
        _print_response_json(f"{name} response JSON", data2)
        return _fail(name, f"HTTP {r2.status_code}")

    out2 = _extract_output_items(data2)
    text2 = (_extract_assistant_text(out2) or "").strip()
    if text2 != nonce:
        _print_response_json(f"{name} response JSON", data2)
        return _fail(name, f"unexpected nonce: {text2!r} (expected {nonce!r})")
    return _ok(name, "previous_response_id ok")


def scenario_stream_text(ctx: RunContext) -> ScenarioResult:
    name = "stream_text"
    expected = "STREAM_OK_OB_PROBE"
    payload = {
        "model": ctx.model,
        "instructions": f"Reply with exactly {expected!r} and nothing else.",
        "input": "ping",
        "temperature": 0,
        "max_output_tokens": 32,
        "stream": True,
        "store": True,
    }
    if ctx.print_requests:
        _print_response_json(f"{name} request", payload)
    r, events = _responses_create_stream(
        base_url=ctx.base_url,
        headers=ctx.headers,
        timeout_s=ctx.timeout_s,
        verify=ctx.verify,
        payload=payload,
    )
    _print_http_summary(f"{name} response (stream)", r)
    if r.status_code >= 400:
        console.print(_panel("Raw SSE (first 30 events)", _pretty(events[:30])))
        return _fail(name, f"HTTP {r.status_code}")

    response = _get_completed_response_from_events(events)
    output_items = _extract_output_items(response)
    text = (_extract_assistant_text(output_items) or "").strip()
    if text != expected:
        console.print(_panel("SSE events (first 30)", _pretty(events[:30])))
        return _fail(name, f"unexpected assistant text: {text!r}")

    delta_events = [e for e in events if e.get("event") == "response.output_text.delta"]
    done_events = [e for e in events if e.get("event") == "response.output_text.done"]
    if not delta_events or not done_events:
        return _warn(name, "missing output_text delta/done events (content may be empty or provider behavior differs)")
    return _ok(name, "streaming text events ok")


def scenario_stream_tool_call(ctx: RunContext) -> ScenarioResult:
    name = "stream_tool_call"
    req = _build_tool_call_request_builtin(
        model=ctx.model,
        tool_type=ctx.tool,
        patch=ctx.patch,
        shell_command=ctx.shell_command,
        stream=True,
    )
    if ctx.print_requests:
        _print_response_json(f"{name} request", req)
    r, events = _responses_create_stream(
        base_url=ctx.base_url,
        headers=ctx.headers,
        timeout_s=ctx.timeout_s,
        verify=ctx.verify,
        payload=req,
    )
    _print_http_summary(f"{name} response (stream)", r)
    if r.status_code >= 400:
        console.print(_panel("Raw SSE (first 30 events)", _pretty(events[:30])))
        return _fail(name, f"HTTP {r.status_code}")

    response = _get_completed_response_from_events(events)
    output_items = _extract_output_items(response)
    call_item = _extract_first_call_item(output_items)
    if call_item is None:
        console.print(_panel("SSE events (first 30)", _pretty(events[:30])))
        return _fail(name, "missing tool call item in completed response")
    if call_item.type != f"{ctx.tool}_call":
        return _fail(name, f"unexpected tool call item.type: {call_item.type!r}")

    delta_events = [
        e for e in events if e.get("event") == "response.function_call_arguments.delta"
    ]
    done_events = [
        e for e in events if e.get("event") == "response.function_call_arguments.done"
    ]
    if not done_events:
        return _warn(name, "missing function_call_arguments.done (provider/tool may not stream args)")
    if not delta_events:
        return _warn(name, "missing function_call_arguments.delta (provider/tool may not stream args)")
    return _ok(name, "streaming tool-call events ok")


def scenario_function_tool_loop(ctx: RunContext) -> ScenarioResult:
    name = "function_tool_loop"
    tool_name = "probe_get_weather"
    args_obj = {"location": "Paris, France", "unit": "C"}
    tool_def = {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": "Return a JSON object with weather info.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string"},
                    "unit": {"type": "string", "enum": ["C", "F"]},
                },
                "required": ["location"],
                "additionalProperties": False,
            },
        },
    }

    req1 = {
        "model": ctx.model,
        "instructions": (
            "You are a tool-calling assistant. "
            "You MUST call the only available tool exactly once and output no normal text."
        ),
        "input": (
            "Call the only available tool with exactly one argument object.\n"
            "The argument object MUST match the following JSON object (no extra keys):\n"
            "<ARGS_JSON>\n"
            f"{_pretty(args_obj)}\n"
            "</ARGS_JSON>\n"
            "Do not wrap the JSON in markdown fences."
        ),
        "tools": [tool_def],
        "tool_choice": "required",
        "temperature": 0,
        "max_output_tokens": 200,
        "stream": False,
        "store": True,
    }
    if ctx.print_requests:
        _print_response_json(f"{name} request #1", req1)
    r1, data1 = _responses_create(
        base_url=ctx.base_url,
        headers=ctx.headers,
        timeout_s=ctx.timeout_s,
        verify=ctx.verify,
        payload=req1,
    )
    _print_http_summary(f"{name} response #1", r1)
    if r1.status_code >= 400:
        _print_response_json(f"{name} response #1 JSON", data1)
        return _fail(name, f"HTTP {r1.status_code} on request #1")

    output1 = _extract_output_items(data1)
    call = _extract_first_call_item(output1)
    if call is None:
        _print_response_json(f"{name} response #1 JSON", data1)
        return _fail(name, "missing function_call output item")
    if call.type != "function_call" or (call.name or "") != tool_name:
        _print_response_json(f"{name} response #1 JSON", data1)
        return _fail(name, f"unexpected call item: type={call.type!r} name={call.name!r}")

    parsed_args: dict[str, Any] | None = None
    try:
        parsed_args = json.loads(call.arguments or "{}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to json.loads(function_call.arguments): {}", exc)
    if not isinstance(parsed_args, dict) or parsed_args.get("location") != args_obj["location"]:
        _print_response_json(f"{name} response #1 JSON", data1)
        return _fail(name, "function_call.arguments did not match expected args")

    req2 = {
        "model": ctx.model,
        "instructions": "Reply with exactly 'OK' and nothing else.",
        "input": [
            {"type": "function_call", "call_id": call.call_id, "name": tool_name, "arguments": call.arguments},
            {"type": "function_call_output", "call_id": call.call_id, "output": {"temp": 25, "unit": "C"}},
            {"role": "user", "content": "Continue with a normal assistant response."},
        ],
        "temperature": 0,
        "max_output_tokens": 16,
        "stream": False,
        "store": True,
    }
    if ctx.print_requests:
        _print_response_json(f"{name} request #2", req2)
    r2, data2 = _responses_create(
        base_url=ctx.base_url,
        headers=ctx.headers,
        timeout_s=ctx.timeout_s,
        verify=ctx.verify,
        payload=req2,
    )
    _print_http_summary(f"{name} response #2", r2)
    if r2.status_code >= 400:
        _print_response_json(f"{name} response #2 JSON", data2)
        return _fail(name, f"HTTP {r2.status_code} on request #2")

    output2 = _extract_output_items(data2)
    text2 = (_extract_assistant_text(output2) or "").strip()
    if text2 != "OK":
        _print_response_json(f"{name} response #2 JSON", data2)
        return _fail(name, f"unexpected assistant text after tool output: {text2!r}")
    return _ok(name, "function tool loop ok")


def scenario_allowed_tools_filter(ctx: RunContext) -> ScenarioResult:
    name = "allowed_tools_filter"
    # Force tool_choice.allowed_tools to only allow `shell`, even though we declare multiple tools.
    # OpenBridge should filter the upstream tools list accordingly.
    args_obj = {"command": ctx.shell_command, "timeout_ms": 10_000}
    payload = {
        "model": ctx.model,
        "instructions": (
            "You are a tool-calling assistant. "
            "You MUST call the only available tool exactly once and output no normal text."
        ),
        "input": (
            "Call the only available tool with exactly one argument object.\n"
            "The argument object MUST match the following JSON object (no extra keys):\n"
            "<ARGS_JSON>\n"
            f"{_pretty(args_obj)}\n"
            "</ARGS_JSON>\n"
            "Do not wrap the JSON in markdown fences."
        ),
        "tools": [{"type": "apply_patch"}, {"type": "shell"}],
        "tool_choice": {"type": "allowed_tools", "mode": "required", "tools": [{"type": "shell"}]},
        "temperature": 0,
        "max_output_tokens": 200,
        "stream": False,
        "store": True,
    }
    if ctx.print_requests:
        _print_response_json(f"{name} request", payload)
    r, data = _responses_create(
        base_url=ctx.base_url,
        headers=ctx.headers,
        timeout_s=ctx.timeout_s,
        verify=ctx.verify,
        payload=payload,
    )
    _print_http_summary(f"{name} response", r)
    if r.status_code >= 400:
        _print_response_json(f"{name} response JSON", data)
        return _fail(name, f"HTTP {r.status_code}")

    output = _extract_output_items(data)
    call = _extract_first_call_item(output)
    if call is None:
        _print_response_json(f"{name} response JSON", data)
        return _fail(name, "missing tool call item")
    if call.type != "shell_call":
        _print_response_json(f"{name} response JSON", data)
        return _fail(name, f"unexpected tool call item.type: {call.type!r} (expected 'shell_call')")
    return _ok(name, "allowed_tools filtered tools ok")


def scenario_tool_name_collision_rejected(ctx: RunContext) -> ScenarioResult:
    name = "tool_name_collision_rejected"
    payload = {
        "model": ctx.model,
        "instructions": "Reply with exactly 'OK' and nothing else.",
        "input": "ping",
        "tools": [
            {"type": "apply_patch"},
            {
                "type": "function",
                "function": {
                    "name": "apply_patch",
                    "description": "Intentionally collides with the built-in apply_patch tool.",
                    "parameters": {
                        "type": "object",
                        "properties": {"input": {"type": "string"}},
                        "required": ["input"],
                        "additionalProperties": False,
                    },
                },
            }
        ],
        "tool_choice": "none",
        "temperature": 0,
        "max_output_tokens": 16,
        "stream": False,
        "store": True,
    }
    if ctx.print_requests:
        _print_response_json(f"{name} request", payload)
    r, data = _responses_create(
        base_url=ctx.base_url,
        headers=ctx.headers,
        timeout_s=ctx.timeout_s,
        verify=ctx.verify,
        payload=payload,
    )
    _print_http_summary(f"{name} response", r)
    if r.status_code != 400:
        _print_response_json(f"{name} response JSON", data)
        return _fail(name, f"expected HTTP 400, got {r.status_code}")
    detail = data.get("detail")
    if not isinstance(detail, str) or "Tool name collision" not in detail:
        _print_response_json(f"{name} response JSON", data)
        return _warn(name, "got HTTP 400 but detail did not mention tool name collision")
    return _ok(name, "tool name collision rejected")


def scenario_structured_outputs_json_schema(ctx: RunContext) -> ScenarioResult:
    name = "structured_outputs_json_schema"
    schema = {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "n": {"type": "integer"},
        },
        "required": ["answer", "n"],
        "additionalProperties": False,
    }
    payload = {
        "model": ctx.model,
        "instructions": "Return a JSON object that matches the provided schema.",
        "input": "Set answer to 'ok' and n to 3.",
        "temperature": 0,
        "max_output_tokens": 64,
        "stream": False,
        "store": True,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "probe_schema",
                "strict": True,
                "schema": schema,
            }
        },
    }
    if ctx.print_requests:
        _print_response_json(f"{name} request", payload)
    r, data = _responses_create(
        base_url=ctx.base_url,
        headers=ctx.headers,
        timeout_s=ctx.timeout_s,
        verify=ctx.verify,
        payload=payload,
    )
    _print_http_summary(f"{name} response", r)
    if r.status_code >= 400:
        _print_response_json(f"{name} response JSON", data)
        return _fail(name, f"HTTP {r.status_code}")

    output = _extract_output_items(data)
    text = _extract_assistant_text(output)
    if not text:
        _print_response_json(f"{name} response JSON", data)
        return _fail(name, "missing assistant output text")

    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        _print_response_json(f"{name} response JSON", data)
        return _fail(name, "assistant text was not valid JSON")
    if not isinstance(obj, dict):
        return _fail(name, "assistant JSON is not an object")
    if obj.get("answer") != "ok" or obj.get("n") != 3:
        _print_response_json(f"{name} response JSON", data)
        return _fail(name, f"unexpected JSON content: {obj!r}")
    extra_keys = set(obj.keys()) - {"answer", "n"}
    if extra_keys:
        return _warn(name, f"unexpected extra keys: {sorted(extra_keys)!r}")
    return _ok(name, "json_schema output ok")


def scenario_state_endpoints(ctx: RunContext) -> ScenarioResult:
    name = "state_endpoints"
    response_id = ctx.shared.get("basic_response_id")
    if not isinstance(response_id, str) or not response_id:
        return _skip(name, "missing basic_response_id; run basic_text first")

    r_get, data_get = _http_get(
        base_url=ctx.base_url,
        headers=ctx.headers,
        timeout_s=ctx.timeout_s,
        verify=ctx.verify,
        path=f"/v1/responses/{response_id}",
    )
    _print_http_summary(f"{name} GET", r_get)
    if r_get.status_code == 501:
        _print_response_json(f"{name} GET JSON", data_get)
        return _skip(name, "state store disabled (HTTP 501)")
    if r_get.status_code >= 400:
        _print_response_json(f"{name} GET JSON", data_get)
        return _fail(name, f"GET failed: HTTP {r_get.status_code}")

    if data_get.get("id") != response_id:
        _print_response_json(f"{name} GET JSON", data_get)
        return _warn(name, "GET returned a different response id than expected")

    r_del, data_del = _http_delete(
        base_url=ctx.base_url,
        headers=ctx.headers,
        timeout_s=ctx.timeout_s,
        verify=ctx.verify,
        path=f"/v1/responses/{response_id}",
    )
    _print_http_summary(f"{name} DELETE", r_del)
    if r_del.status_code >= 400:
        _print_response_json(f"{name} DELETE JSON", data_del)
        return _fail(name, f"DELETE failed: HTTP {r_del.status_code}")

    r_get2, data_get2 = _http_get(
        base_url=ctx.base_url,
        headers=ctx.headers,
        timeout_s=ctx.timeout_s,
        verify=ctx.verify,
        path=f"/v1/responses/{response_id}",
    )
    _print_http_summary(f"{name} GET after DELETE", r_get2)
    if r_get2.status_code not in (404, 501):
        _print_response_json(f"{name} GET2 JSON", data_get2)
        return _warn(name, f"expected 404/501 after DELETE, got {r_get2.status_code}")
    return _ok(name, "GET/DELETE ok (when enabled)")


def scenario_store_false(ctx: RunContext) -> ScenarioResult:
    name = "store_false"
    payload = {
        "model": ctx.model,
        "instructions": "Reply with exactly 'STORED_FALSE_OK' and nothing else.",
        "input": "ping",
        "temperature": 0,
        "max_output_tokens": 16,
        "stream": False,
        "store": False,
    }
    if ctx.print_requests:
        _print_response_json(f"{name} request", payload)
    r, data = _responses_create(
        base_url=ctx.base_url,
        headers=ctx.headers,
        timeout_s=ctx.timeout_s,
        verify=ctx.verify,
        payload=payload,
    )
    _print_http_summary(f"{name} response", r)
    if r.status_code >= 400:
        _print_response_json(f"{name} response JSON", data)
        return _fail(name, f"HTTP {r.status_code}")

    response_id = data.get("id")
    if not isinstance(response_id, str) or not response_id:
        return _fail(name, "missing response id")

    r_get, data_get = _http_get(
        base_url=ctx.base_url,
        headers=ctx.headers,
        timeout_s=ctx.timeout_s,
        verify=ctx.verify,
        path=f"/v1/responses/{response_id}",
    )
    _print_http_summary(f"{name} GET", r_get)
    if r_get.status_code == 501:
        _print_response_json(f"{name} GET JSON", data_get)
        return _skip(name, "state store disabled (HTTP 501)")
    if r_get.status_code != 404:
        _print_response_json(f"{name} GET JSON", data_get)
        return _warn(name, f"expected 404 for store=false response, got {r_get.status_code}")

    r_prev, data_prev = _responses_create(
        base_url=ctx.base_url,
        headers=ctx.headers,
        timeout_s=ctx.timeout_s,
        verify=ctx.verify,
        payload={
            "model": ctx.model,
            "instructions": "Reply with exactly 'OK' and nothing else.",
            "input": "ping",
            "previous_response_id": response_id,
            "temperature": 0,
            "max_output_tokens": 16,
            "stream": False,
            "store": True,
        },
    )
    _print_http_summary(f"{name} previous_response_id", r_prev)
    if r_prev.status_code == 404:
        return _ok(name, "store=false not persisted (404 as expected)")
    if r_prev.status_code == 501:
        return _skip(name, "state store disabled (HTTP 501)")
    _print_response_json(f"{name} previous_response_id JSON", data_prev)
    return _warn(name, f"expected 404/501 for previous_response_id, got {r_prev.status_code}")


def _scenario_catalog() -> dict[str, ScenarioFn]:
    return {
        "basic_text": scenario_basic_text,
        "tool_loop_builtin": scenario_tool_loop_builtin,
        "multi_turn_stateless": scenario_multi_turn_stateless,
        "multi_turn_stateful": scenario_multi_turn_stateful,
        "stream_text": scenario_stream_text,
        "stream_tool_call": scenario_stream_tool_call,
        "function_tool_loop": scenario_function_tool_loop,
        "allowed_tools_filter": scenario_allowed_tools_filter,
        "tool_name_collision_rejected": scenario_tool_name_collision_rejected,
        "structured_outputs_json_schema": scenario_structured_outputs_json_schema,
        "state_endpoints": scenario_state_endpoints,
        "store_false": scenario_store_false,
    }


def _suite_to_scenarios(suite: str) -> list[str]:
    suites: dict[str, list[str]] = {
        "quick": ["tool_loop_builtin"],
        "smoke": [
            "basic_text",
            "tool_loop_builtin",
            "multi_turn_stateless",
            "stream_text",
        ],
        "full": [
            "basic_text",
            "tool_loop_builtin",
            "multi_turn_stateless",
            "multi_turn_stateful",
            "stream_text",
            "stream_tool_call",
            "function_tool_loop",
            "allowed_tools_filter",
            "tool_name_collision_rejected",
            "structured_outputs_json_schema",
            "state_endpoints",
            "store_false",
        ],
    }
    if suite not in suites:
        raise SystemExit(f"Unknown suite: {suite!r}. Valid: {sorted(suites.keys())}")
    return suites[suite]


def _run_scenarios(ctx: RunContext, scenario_names: list[str]) -> list[ScenarioResult]:
    catalog = _scenario_catalog()
    results: list[ScenarioResult] = []

    unknown = [name for name in scenario_names if name not in catalog]
    if unknown:
        raise SystemExit(
            f"Unknown scenarios: {unknown!r}\n\nValid scenarios:\n  "
            + "\n  ".join(sorted(catalog.keys()))
        )

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Running scenarios", total=len(scenario_names))
        for name in scenario_names:
            progress.update(task_id, description=f"Running {name}")
            console.print(_panel("Scenario", f"{name}\n{catalog[name].__name__}"))
            try:
                result = catalog[name](ctx)
            except AssertionError as exc:
                result = _fail(name, str(exc))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Scenario {} raised an exception", name)
                result = _fail(name, f"unhandled exception: {exc}")
            results.append(result)
            progress.advance(task_id, 1)
    return results


def _print_summary(results: list[ScenarioResult]) -> None:
    table = Table(title="OpenBridge probe summary")
    table.add_column("scenario", style="bold")
    table.add_column("status")
    table.add_column("detail")
    for r in results:
        table.add_row(r.name, r.status.value, r.detail)
    console.print(table)


def _exit_code(results: list[ScenarioResult]) -> int:
    if any(r.status == Status.FAIL for r in results):
        return 1
    return 0


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Probe OpenBridge /v1/responses proxy and compatibility behaviors."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="OpenBridge base URL")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Responses model name (OpenBridge resolves it)")
    parser.add_argument("--tool", default=DEFAULT_TOOL, help="Built-in tool type to probe (default: apply_patch)")
    parser.add_argument(
        "--suite",
        default=DEFAULT_SUITE,
        choices=["quick", "smoke", "full"],
        help="Scenario suite to run",
    )
    parser.add_argument(
        "--scenarios",
        nargs="*",
        default=None,
        help="Run specific scenarios (overrides --suite). Use --list-scenarios to see options.",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="Print available scenario names and exit",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Legacy: stream the first request of tool_loop_builtin (kept for compatibility).",
    )
    parser.add_argument(
        "--stateless",
        action="store_true",
        help="Force stateless behavior in tool_loop_builtin (do not use previous_response_id).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help="HTTP timeout in seconds",
    )
    parser.add_argument(
        "--client-api-key",
        default=os.getenv("OPENBRIDGE_CLIENT_API_KEY"),
        help="Optional client API key if OpenBridge requires it (also reads OPENBRIDGE_CLIENT_API_KEY).",
    )
    parser.add_argument(
        "--patch-file",
        default=None,
        help="Path to a patch file used as tool argument payload.",
    )
    parser.add_argument(
        "--shell-command",
        default=DEFAULT_SHELL_COMMAND,
        help="Shell command used when --tool shell.",
    )
    parser.add_argument(
        "--tls-insecure",
        action="store_true",
        help="Disable TLS verification (useful with https://127.0.0.1 and self-signed certs).",
    )
    parser.add_argument("--print-requests", action="store_true", help="Print request JSON payloads")
    parser.add_argument("--log-level", default="INFO", help="Loguru level (INFO/DEBUG/...)")
    args = parser.parse_args(argv)

    _setup_logging(args.log_level)

    if args.list_scenarios:
        names = sorted(_scenario_catalog().keys())
        console.print(_panel("Available scenarios", "\n".join(names)))
        return 0

    base_url = str(args.base_url)
    headers = _headers(args.client_api_key)
    verify = not bool(args.tls_insecure)
    _require_server_up(base_url, headers, args.timeout, verify=verify)

    patch = DEFAULT_PATCH
    if args.patch_file:
        with open(args.patch_file, "r", encoding="utf-8") as f:
            patch = f.read()

    scenario_names: list[str]
    if args.scenarios is not None and len(args.scenarios) > 0:
        scenario_names = [str(x) for x in args.scenarios]
    else:
        scenario_names = _suite_to_scenarios(str(args.suite))

    console.print(
        _panel(
            "Target",
            "base_url={}\nmodel={}\ntool={}\nlegacy_stream_tool_call={}\nforce_stateless={}\nsuite={}\nscenarios={}".format(
                base_url,
                args.model,
                args.tool,
                bool(args.stream),
                bool(args.stateless),
                args.suite,
                ", ".join(scenario_names),
            ),
        )
    )

    ctx = RunContext(
        base_url=base_url,
        headers=headers,
        timeout_s=float(args.timeout),
        verify=verify,
        model=str(args.model),
        tool=str(args.tool),
        patch=patch,
        shell_command=str(args.shell_command),
        legacy_stream_tool_call=bool(args.stream),
        force_stateless=bool(args.stateless),
        print_requests=bool(args.print_requests),
        shared={},
    )

    results = _run_scenarios(ctx, scenario_names)
    _print_summary(results)
    return _exit_code(results)


def main() -> None:
    raise SystemExit(_main(sys.argv[1:]))


if __name__ == "__main__":
    main()

