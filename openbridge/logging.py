from __future__ import annotations

from loguru import logger
from rich.console import Console
from rich.text import Text
from rich.traceback import install as install_rich_traceback


def setup_logging(level: str, *, log_file: str | None = None) -> None:
    console = Console()
    install_rich_traceback(console=console, show_locals=False)
    logger.remove()
    logger.configure(extra={"request_id": "-", "upstream_request_id": "-"})

    def _sink(message: object) -> None:
        record = message.record  # type: ignore[attr-defined]
        timestamp = record["time"].strftime("%Y-%m-%d %H:%M:%S")
        level_name = record["level"].name
        request_id = record["extra"].get("request_id", "-")
        upstream_id = record["extra"].get("upstream_request_id", "-")
        text = Text(
            f"{timestamp} | {level_name:<8} | {request_id} | {upstream_id} | {record['message']}"
        )
        if record["exception"]:
            text.append(f"\n{record['exception']}")
        console.print(text)

    logger.add(_sink, level=level, backtrace=False, diagnose=False)
    if log_file:
        logger.add(
            log_file,
            level=level,
            backtrace=False,
            diagnose=False,
            enqueue=True,
            format=(
                "{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | "
                "{extra[request_id]} | {extra[upstream_request_id]} | {message}\n{exception}"
            ),
        )


def get_logger() -> "logger":  # type: ignore[name-defined]
    return logger
