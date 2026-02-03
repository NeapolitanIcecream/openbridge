from __future__ import annotations

from loguru import logger
from rich.console import Console
from rich.text import Text
from rich.traceback import install as install_rich_traceback


def _compact_id(value: object) -> str:
    """Compact long request IDs for readable console logs."""
    if value is None:
        return "-"
    s = str(value).strip()
    if not s:
        return "-"
    if "_" in s:
        prefix, rest = s.split("_", 1)
        if len(rest) <= 16:
            return s
        return f"{prefix}_{rest[:8]}…{rest[-4:]}"
    if len(s) <= 16:
        return s
    return f"{s[:8]}…{s[-4:]}"


def _level_style(level_name: str) -> str:
    level = level_name.upper()
    if level in {"TRACE", "DEBUG"}:
        return "dim"
    if level in {"INFO", "SUCCESS"}:
        return "green"
    if level == "WARNING":
        return "yellow"
    if level == "ERROR":
        return "red"
    if level == "CRITICAL":
        return "bold red"
    return ""


def setup_logging(level: str, *, log_file: str | None = None) -> None:
    console = Console()
    install_rich_traceback(console=console, show_locals=False)
    logger.remove()
    logger.configure(extra={"request_id": "-", "upstream_request_id": "-"})

    def _sink(message: object) -> None:
        record = message.record  # type: ignore[attr-defined]
        timestamp = record["time"].strftime("%Y-%m-%d %H:%M:%S")
        level_name = record["level"].name
        request_id = _compact_id(record["extra"].get("request_id", "-"))
        upstream_id = _compact_id(record["extra"].get("upstream_request_id", "-"))

        text = Text(justify="left", overflow="ellipsis", no_wrap=True)
        text.append(timestamp, style="dim")
        text.append(" | ", style="dim")
        text.append(f"{level_name:<8}", style=_level_style(level_name))
        text.append(" | ", style="dim")
        text.append(f"{request_id:<18}", style="cyan")
        text.append(" | ", style="dim")
        text.append(f"{upstream_id:<18}", style="magenta")
        text.append(" | ", style="dim")

        msg = Text(str(record["message"]))
        if msg.plain.startswith("REQ "):
            msg.stylize("bold cyan", 0, 3)
        text.append(msg)
        if record["exception"]:
            text.no_wrap = False
            text.overflow = "fold"
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
