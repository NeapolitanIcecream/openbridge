from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import httpx
import typer
from pydantic import ValidationError
from rich.console import Console
from rich.syntax import Syntax

from openbridge import __version__
from openbridge.config import Settings, load_settings, reset_settings_cache
from openbridge.logging import get_logger, setup_logging


_error_console = Console(stderr=True)
_console = Console()


def _version_callback(value: bool) -> None:
    if not value:
        return
    typer.echo(__version__)
    raise typer.Exit()


app = typer.Typer(
    help="OpenBridge: OpenAI Responses API to OpenRouter Chat Completions bridge.",
    add_completion=False,
    rich_markup_mode="rich",
)


def _run_server(
    *,
    host: str | None,
    port: int | None,
    reload: bool,
    debug_endpoints: bool,
    trace: bool,
    trace_log: bool,
    trace_content: str | None,
    trace_max_chars: int | None,
    log_file: Path | None,
) -> None:
    if debug_endpoints:
        os.environ["OPENBRIDGE_DEBUG_ENDPOINTS"] = "1"
    if trace:
        os.environ["OPENBRIDGE_TRACE_ENABLED"] = "1"
    if trace_log:
        os.environ["OPENBRIDGE_TRACE_LOG"] = "1"
    if trace_content is not None:
        os.environ["OPENBRIDGE_TRACE_CONTENT"] = str(trace_content)
    if trace_max_chars is not None:
        os.environ["OPENBRIDGE_TRACE_MAX_CHARS"] = str(int(trace_max_chars))
    if log_file is not None:
        os.environ["OPENBRIDGE_LOG_FILE"] = str(log_file)

    reset_settings_cache()
    try:
        settings = load_settings()
    except ValidationError as exc:
        _print_settings_validation_error(exc)
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        _error_console.print(f"[bold red]Configuration error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    host = host or settings.openbridge_host
    port = port or settings.openbridge_port

    setup_logging(
        settings.openbridge_log_level,
        log_file=str(settings.openbridge_log_file) if settings.openbridge_log_file else None,
    )
    logger = get_logger()
    scheme = "https" if settings.openbridge_ssl_certfile else "http"
    logger.info("Starting OpenBridge on {}://{}:{}", scheme, host, port)

    import uvicorn

    uvicorn.run(
        "openbridge.app:app",
        host=host,
        port=port,
        reload=reload,
        log_config=None,
        ssl_certfile=str(settings.openbridge_ssl_certfile)
        if settings.openbridge_ssl_certfile
        else None,
        ssl_keyfile=str(settings.openbridge_ssl_keyfile)
        if settings.openbridge_ssl_keyfile
        else None,
        ssl_keyfile_password=settings.openbridge_ssl_keyfile_password,
    )


def _print_settings_validation_error(exc: ValidationError) -> None:
    details: list[str] = []
    for err in exc.errors():
        loc = err.get("loc") or ()
        field = loc[-1] if loc else "settings"

        if isinstance(field, str) and field in Settings.model_fields:
            alias = Settings.model_fields[field].alias or field
        else:
            alias = str(field)

        msg = err.get("msg") or "Invalid value"
        details.append(f"{alias}: {msg}")

    _error_console.print("[bold red]OpenBridge configuration error[/bold red]")
    for line in details:
        _error_console.print(f"[red]- {line}[/red]")
    _error_console.print(
        "[dim]Fix your environment variables or .env file and retry. "
        "Required: OPENROUTER_API_KEY.[/dim]"
    )


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
    host: Annotated[
        str | None,
        typer.Option(
            "--host",
            help="Bind host. Defaults to OPENBRIDGE_HOST / settings default.",
        ),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option(
            "--port",
            help="Bind port. Defaults to OPENBRIDGE_PORT / settings default.",
        ),
    ] = None,
    reload: Annotated[
        bool,
        typer.Option(
            "--reload",
            help="Enable auto-reload (development only).",
        ),
    ] = False,
    debug_endpoints: Annotated[
        bool,
        typer.Option(
            "--debug-endpoints",
            help="Enable debug endpoints under /v1/debug/* (local dev only).",
        ),
    ] = False,
    trace: Annotated[
        bool,
        typer.Option(
            "--trace",
            help="Enable trace capture for debugging.",
        ),
    ] = False,
    trace_log: Annotated[
        bool,
        typer.Option(
            "--trace-log",
            help="Log sanitized trace payloads (may be large).",
        ),
    ] = False,
    trace_content: Annotated[
        str | None,
        typer.Option(
            "--trace-content",
            help="Trace content mode: none|truncate|full.",
        ),
    ] = None,
    trace_max_chars: Annotated[
        int | None,
        typer.Option(
            "--trace-max-chars",
            help="Max chars per field when trace-content=truncate.",
        ),
    ] = None,
    log_file: Annotated[
        Path | None,
        typer.Option(
            "--log-file",
            help="Write logs to a file (in addition to console).",
        ),
    ] = None,
) -> None:
    """Start the OpenBridge server (default command)."""
    if ctx.invoked_subcommand is not None:
        return
    _run_server(
        host=host,
        port=port,
        reload=reload,
        debug_endpoints=debug_endpoints,
        trace=trace,
        trace_log=trace_log,
        trace_content=trace_content,
        trace_max_chars=trace_max_chars,
        log_file=log_file,
    )


@app.command("serve")
def serve(
    host: Annotated[
        str | None,
        typer.Option(
            "--host",
            help="Bind host. Defaults to OPENBRIDGE_HOST / settings default.",
        ),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option(
            "--port",
            help="Bind port. Defaults to OPENBRIDGE_PORT / settings default.",
        ),
    ] = None,
    reload: Annotated[
        bool,
        typer.Option(
            "--reload",
            help="Enable auto-reload (development only).",
        ),
    ] = False,
    debug_endpoints: Annotated[
        bool,
        typer.Option(
            "--debug-endpoints",
            help="Enable debug endpoints under /v1/debug/* (local dev only).",
        ),
    ] = False,
    trace: Annotated[
        bool,
        typer.Option(
            "--trace",
            help="Enable trace capture for debugging.",
        ),
    ] = False,
    trace_log: Annotated[
        bool,
        typer.Option(
            "--trace-log",
            help="Log sanitized trace payloads (may be large).",
        ),
    ] = False,
    trace_content: Annotated[
        str | None,
        typer.Option(
            "--trace-content",
            help="Trace content mode: none|truncate|full.",
        ),
    ] = None,
    trace_max_chars: Annotated[
        int | None,
        typer.Option(
            "--trace-max-chars",
            help="Max chars per field when trace-content=truncate.",
        ),
    ] = None,
    log_file: Annotated[
        Path | None,
        typer.Option(
            "--log-file",
            help="Write logs to a file (in addition to console).",
        ),
    ] = None,
) -> None:
    """Start the OpenBridge server."""
    _run_server(
        host=host,
        port=port,
        reload=reload,
        debug_endpoints=debug_endpoints,
        trace=trace,
        trace_log=trace_log,
        trace_content=trace_content,
        trace_max_chars=trace_max_chars,
        log_file=log_file,
    )


def _default_base_url() -> str:
    host = os.environ.get("OPENBRIDGE_HOST", "127.0.0.1")
    port_raw = os.environ.get("OPENBRIDGE_PORT", "8000")
    try:
        port = int(port_raw)
    except ValueError:
        port = 8000
    return f"http://{host}:{port}"


@app.command("debug")
def debug(
    trace_id: Annotated[
        str,
        typer.Argument(
            ...,
            help="Trace id: response id (resp_*) or request id (req_*).",
        ),
    ],
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            help="OpenBridge base URL (defaults to http://OPENBRIDGE_HOST:OPENBRIDGE_PORT).",
        ),
    ] = None,
    kind: Annotated[
        str,
        typer.Option(
            "--kind",
            help="Trace kind: auto|response|request.",
        ),
    ] = "auto",
    api_key: Annotated[
        str | None,
        typer.Option(
            "--api-key",
            envvar="OPENBRIDGE_CLIENT_API_KEY",
            help="Client API key for OpenBridge (Authorization: Bearer ...).",
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Write the debug bundle JSON to a file.",
        ),
    ] = None,
    raw: Annotated[
        bool,
        typer.Option(
            "--raw",
            help="Print raw JSON to stdout (no rich formatting).",
        ),
    ] = False,
) -> None:
    base_url = (base_url or _default_base_url()).rstrip("/")
    kind_norm = (kind or "auto").strip().lower()
    if kind_norm == "auto":
        if trace_id.startswith("req_"):
            kind_norm = "request"
        elif trace_id.startswith("resp_"):
            kind_norm = "response"
        else:
            raise typer.BadParameter(
                "Unable to infer kind from id. Use --kind request|response."
            )
    if kind_norm not in {"request", "response"}:
        raise typer.BadParameter("kind must be auto|request|response")

    if kind_norm == "request":
        url = f"{base_url}/v1/debug/requests/{trace_id}"
    else:
        url = f"{base_url}/v1/debug/responses/{trace_id}"

    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = httpx.get(url, headers=headers, timeout=15.0)
    except httpx.RequestError as exc:
        _error_console.print(f"[bold red]Request failed:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    if resp.status_code >= 400:
        body = resp.text
        try:
            body = json.dumps(resp.json(), ensure_ascii=False, indent=2)
        except ValueError:
            pass
        _error_console.print(f"[bold red]HTTP {resp.status_code}[/bold red]")
        _error_console.print(body)
        raise typer.Exit(code=1)

    data = resp.json()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if output is not None:
        output.write_text(text + "\n", encoding="utf-8")
        _console.print(f"[dim]Wrote debug bundle to {output}[/dim]")

    if raw:
        typer.echo(text)
        return

    _console.print(Syntax(text, "json", word_wrap=False))

