from __future__ import annotations

from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console

from openbridge import __version__
from openbridge.config import Settings, load_settings
from openbridge.logging import get_logger, setup_logging


_error_console = Console(stderr=True)


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
) -> None:
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

    setup_logging(settings.openbridge_log_level)
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
) -> None:
    """Start the OpenBridge server (default command)."""
    if ctx.invoked_subcommand is not None:
        return
    _run_server(host=host, port=port, reload=reload)


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
) -> None:
    """Start the OpenBridge server."""
    _run_server(host=host, port=port, reload=reload)

