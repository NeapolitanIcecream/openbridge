from __future__ import annotations

from typing import Annotated

import typer
import uvicorn

from openbridge import __version__
from openbridge.config import load_settings
from openbridge.logging import get_logger, setup_logging


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
    settings = load_settings()
    host = host or settings.openbridge_host
    port = port or settings.openbridge_port

    setup_logging(settings.openbridge_log_level)
    logger = get_logger()
    scheme = "https" if settings.openbridge_ssl_certfile else "http"
    logger.info("Starting OpenBridge on {}://{}:{}", scheme, host, port)

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

