#!/usr/bin/env python3
"""
Probe whether OpenBridge correctly:
1) Proxies OpenAI Responses API requests to OpenRouter Chat Completions upstream.
2) Handles OpenAI Responses built-in tool calls via tool virtualization (e.g. apply_patch).

This script acts like a minimal Responses client:
- First request: forces a built-in tool call (apply_patch by default).
- Second request: sends back a *_call_output item and expects a normal assistant message.

Notes:
- OpenBridge must be running (default: http://127.0.0.1:8000).
- OpenBridge server must be configured with OPENROUTER_API_KEY so it can reach upstream.
- This script does NOT execute any tool; it only simulates tool output.
- If your client uses https:// against an HTTP OpenBridge server, the server will log
  `Invalid HTTP request received.` and the client will disconnect. Use an http:// base URL
  or enable TLS on OpenBridge.

Usage:
  uv run python docs/openbridge_responses_proxy_probe.py
  uv run python docs/openbridge_responses_proxy_probe.py --stream
  uv run python docs/openbridge_responses_proxy_probe.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_MODEL = "gpt-5.2-codex"
DEFAULT_TIMEOUT_S = 120.0
DEFAULT_TOOL = "apply_patch"

DEFAULT_PATCH = """*** Begin Patch
*** Add File: probe.txt
+hello from OpenBridge probe
*** End Patch
"""

DEFAULT_SHELL_COMMAND = "echo 'hello from OpenBridge probe'"


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
            "  uv run python main.py\n\n"
            f"Then retry. Root cause: {exc}"
        ) from exc


@dataclass(frozen=True)
class ToolCall:
    type: str
    call_id: str
    name: str | None
    arguments: str | None


def _extract_first_tool_call(output_items: Iterable[dict[str, Any]]) -> ToolCall | None:
    for item in output_items:
        item_type = str(item.get("type") or "")
        call_id = str(item.get("call_id") or "")
        if not item_type.endswith("_call") or not call_id:
            continue
        return ToolCall(
            type=item_type,
            call_id=call_id,
            name=item.get("name"),
            arguments=item.get("arguments"),
        )
    return None


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


def _build_tool_call_request(
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
            "The argument object MUST have exactly one key: `patch`.\n"
            "Set `patch` to EXACTLY the following string (including newlines), without adding any extra characters:\n"
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


def _build_tool_output_request(
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


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Probe OpenBridge /v1/responses proxy and built-in tool virtualization."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="OpenBridge base URL")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Responses model name (OpenBridge resolves it)")
    parser.add_argument("--tool", default=DEFAULT_TOOL, help="Built-in tool type to probe (default: apply_patch)")
    parser.add_argument("--stream", action="store_true", help="Use stream=true and parse SSE events")
    parser.add_argument(
        "--stateless",
        action="store_true",
        help="Do not use previous_response_id; resend the tool call item + tool output as input items.",
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

    base_url = str(args.base_url)
    headers = _headers(args.client_api_key)
    verify = not bool(args.tls_insecure)
    _require_server_up(base_url, headers, args.timeout, verify=verify)

    patch = DEFAULT_PATCH
    if args.patch_file:
        with open(args.patch_file, "r", encoding="utf-8") as f:
            patch = f.read()

    console.print(_panel("Target", f"base_url={base_url}\nmodel={args.model}\nstream={args.stream}\ntool={args.tool}"))

    # 1) Force a built-in tool call.
    req1 = _build_tool_call_request(
        model=str(args.model),
        tool_type=str(args.tool),
        patch=patch,
        shell_command=str(args.shell_command),
        stream=bool(args.stream),
    )
    if args.print_requests:
        _print_response_json("Request #1 (create response; force tool call)", req1)

    if args.stream:
        r1, events1 = _responses_create_stream(
            base_url=base_url,
            headers=headers,
            timeout_s=args.timeout,
            verify=verify,
            payload=req1,
        )
        _print_http_summary("Response #1 (stream)", r1)
        if r1.status_code >= 400:
            console.print(_panel("Raw SSE (first 30 events)", _pretty(events1[:30])))
            return 1
        console.print(_panel("SSE events (first 30)", _pretty(events1[:30])))
        completed = next((e for e in events1 if e.get("event") == "response.completed"), None)
        if not completed or not isinstance(completed.get("data"), dict):
            raise SystemExit("Missing response.completed in SSE stream")
        data1 = completed["data"].get("response")
        if not isinstance(data1, dict):
            raise SystemExit("Invalid response.completed payload: missing data.response")
    else:
        r1, data1 = _responses_create(
            base_url=base_url,
            headers=headers,
            timeout_s=args.timeout,
            verify=verify,
            payload=req1,
        )
        _print_http_summary("Response #1 (non-stream)", r1)
        _print_response_json("Response #1 JSON", data1)
        if r1.status_code >= 400:
            return 1

    output1 = data1.get("output") if isinstance(data1, dict) else None
    if not isinstance(output1, list):
        raise SystemExit("Response #1 missing output[]")
    tool_call = _extract_first_tool_call(output1)
    if tool_call is None:
        raise SystemExit("Response #1 did not contain any *_call output item")

    tool_summary = Table(title="Detected tool call (Response #1)")
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
        "tool_type": str(args.tool),
    }
    previous_response_id: str | None = None
    stateless_tool_call_item: ToolCall | None = None
    if not args.stateless and isinstance(data1, dict):
        previous_response_id = str(data1.get("id"))
    else:
        stateless_tool_call_item = tool_call

    req2 = _build_tool_output_request(
        model=str(args.model),
        tool_type=str(args.tool),
        previous_response_id=previous_response_id,
        stateless_with_tool_call_item=stateless_tool_call_item,
        call_id=tool_call.call_id,
        tool_output=tool_output,
        stream=False,
    )
    if args.print_requests:
        _print_response_json("Request #2 (send *_call_output; continue)", req2)

    r2, data2 = _responses_create(
        base_url=base_url,
        headers=headers,
        timeout_s=args.timeout,
        verify=verify,
        payload=req2,
    )
    _print_http_summary("Response #2 (non-stream)", r2)
    _print_response_json("Response #2 JSON", data2)
    if r2.status_code >= 400:
        # If state is disabled, automatically fall back to a stateless retry.
        if (
            not args.stateless
            and previous_response_id is not None
            and r2.status_code in (404, 501)
        ):
            logger.warning(
                "Response #2 failed with status {}. Retrying in stateless mode (no previous_response_id).",
                r2.status_code,
            )
            req2b = _build_tool_output_request(
                model=str(args.model),
                tool_type=str(args.tool),
                previous_response_id=None,
                stateless_with_tool_call_item=tool_call,
                call_id=tool_call.call_id,
                tool_output=tool_output,
                stream=False,
            )
            r2b, data2b = _responses_create(
                base_url=base_url,
                headers=headers,
                timeout_s=args.timeout,
                verify=verify,
                payload=req2b,
            )
            _print_http_summary("Response #2 (stateless retry)", r2b)
            _print_response_json("Response #2 (stateless retry) JSON", data2b)
            if r2b.status_code >= 400:
                return 1
            r2, data2 = r2b, data2b
        else:
            return 1

    output2 = data2.get("output") if isinstance(data2, dict) else None
    if not isinstance(output2, list) or not output2:
        raise SystemExit("Response #2 missing output[]")

    has_message = any(str(item.get("type")) == "message" for item in output2 if isinstance(item, dict))
    has_tool_call = any(str(item.get("type") or "").endswith("_call") for item in output2 if isinstance(item, dict))

    verdict = Table(title="Verdict")
    verdict.add_column("check", style="bold")
    verdict.add_column("result")
    is_response_object = isinstance(data1, dict) and data1.get("object") == "response"
    model_looks_resolved = isinstance(data1, dict) and isinstance(data1.get("model"), str) and "/" in data1.get("model", "")
    verdict.add_row(
        "Responses -> Chat Completions proxy (basic)",
        "PASS" if is_response_object and model_looks_resolved else "WARN",
    )
    verdict.add_row(
        "Built-in tool call virtualization (item.type == <tool>_call)",
        "PASS" if tool_call.type == f"{args.tool}_call" else "FAIL",
    )
    verdict.add_row("Tool loop continues (second response has assistant message)", "PASS" if has_message else "FAIL")
    verdict.add_row("No unexpected tool call in response #2", "PASS" if not has_tool_call else "WARN")
    console.print(verdict)

    return 0


def main() -> None:
    raise SystemExit(_main(sys.argv[1:]))


if __name__ == "__main__":
    main()

