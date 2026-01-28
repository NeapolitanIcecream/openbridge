import uvicorn

from openbridge.config import load_settings
from openbridge.logging import get_logger, setup_logging


def main() -> None:
    settings = load_settings()
    setup_logging(settings.openbridge_log_level)
    logger = get_logger()
    scheme = "https" if settings.openbridge_ssl_certfile else "http"
    logger.info(
        "Starting OpenBridge on {}://{}:{}",
        scheme,
        settings.openbridge_host,
        settings.openbridge_port,
    )
    uvicorn.run(
        "openbridge.app:app",
        host=settings.openbridge_host,
        port=settings.openbridge_port,
        log_config=None,
        ssl_certfile=str(settings.openbridge_ssl_certfile)
        if settings.openbridge_ssl_certfile
        else None,
        ssl_keyfile=str(settings.openbridge_ssl_keyfile)
        if settings.openbridge_ssl_keyfile
        else None,
        ssl_keyfile_password=settings.openbridge_ssl_keyfile_password,
    )


if __name__ == "__main__":
    main()
